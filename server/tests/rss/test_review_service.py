"""CandidateReviewService：待审核查询筛选与排序、本地采纳、忽略状态机。"""

import asyncio
import hashlib
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from reven.rss.models import RssDiscoveryRun, RssItem, RssSource
from reven.rss.review_service import CandidateReviewError, CandidateReviewService
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def make_item(
    source: RssSource,
    run: RssDiscoveryRun,
    marker: str,
    *,
    status: str = "candidate",
    published_at: datetime | None = datetime(2026, 8, 11, 1, tzinfo=UTC),
    review_pushed_at: datetime | None = None,
) -> RssItem:
    return RssItem(
        source_id=source.id,
        first_seen_run_id=run.id,
        source_name=source.name,
        guid=marker,
        url=f"https://example.com/{marker}",
        url_key=digest(f"url-{marker}"),
        guid_key=digest(f"guid-{marker}"),
        title_key=digest(f"title-{marker}"),
        title=f"Title {marker}",
        summary="summary",
        title_zh=f"标题{marker}",
        summary_zh="摘要",
        published_at=published_at,
        status=status,
        review_pushed_at=review_pushed_at,
    )


async def seed_items(db_session: AsyncSession, *items: tuple[str, dict[str, object]]) -> list[RssItem]:
    source = RssSource(name="Example", feed_url="https://example.com/feed", enabled=True)
    run = RssDiscoveryRun(run_date=date(2026, 8, 11))
    db_session.add_all([source, run])
    await db_session.flush()
    seeded = [make_item(source, run, marker, **overrides) for marker, overrides in items]
    db_session.add_all(seeded)
    await db_session.commit()
    return seeded


def build_service(db_session: AsyncSession) -> CandidateReviewService:
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    return CandidateReviewService(factory)


@pytest.mark.anyio
async def test_list_pending_review_filters_and_orders_by_published_at(db_session: AsyncSession) -> None:
    seeded = await seed_items(
        db_session,
        ("old", {"published_at": datetime(2026, 8, 10, 1, tzinfo=UTC)}),
        ("new", {"published_at": datetime(2026, 8, 11, 2, tzinfo=UTC)}),
        ("no-date", {"published_at": None}),
        ("already-pushed", {"review_pushed_at": datetime(2026, 8, 11, 3, tzinfo=UTC)}),
        ("ignored", {"status": "ignored"}),
        ("pending", {"status": "pending"}),
    )

    pending = await build_service(db_session).list_pending_review()

    by_guid = {item.guid: item for item in seeded}
    assert [item.id for item in pending] == [
        by_guid["new"].id,
        by_guid["old"].id,
        by_guid["no-date"].id,
    ]


@pytest.mark.anyio
async def test_approve_saves_locally_and_preserves_original_timestamp(db_session: AsyncSession) -> None:
    seeded = await seed_items(db_session, ("one", {}))
    service = build_service(db_session)

    first = await service.approve(seeded[0].id)
    second = await service.approve(seeded[0].id)

    assert first.id == second.id == seeded[0].id
    assert first.status == second.status == "saved"
    assert first.saved_at is not None
    assert second.saved_at == first.saved_at
    async with async_sessionmaker(db_session.bind, expire_on_commit=False)() as session:
        stored = await session.get(RssItem, seeded[0].id)
        assert stored is not None
        assert stored.status == "saved"
        assert stored.saved_at == first.saved_at
    assert await service.list_pending_review() == []


@pytest.mark.anyio
async def test_approve_missing_candidate_raises_not_found(db_session: AsyncSession) -> None:
    with pytest.raises(CandidateReviewError) as caught:
        await build_service(db_session).approve(uuid4())

    assert caught.value.code == "RSS_CANDIDATE_NOT_FOUND"
    assert caught.value.status_code == 404


@pytest.mark.anyio
@pytest.mark.parametrize("status", ["ignored", "filtered", "pending"])
async def test_approve_rejects_non_candidates(db_session: AsyncSession, status: str) -> None:
    seeded = await seed_items(db_session, ("one", {"status": status}))

    with pytest.raises(CandidateReviewError) as caught:
        await build_service(db_session).approve(seeded[0].id)

    assert caught.value.code == "RSS_CANDIDATE_NOT_SAVABLE"
    assert caught.value.status_code == 409
    await db_session.refresh(seeded[0])
    assert seeded[0].status == status
    assert seeded[0].saved_at is None


@pytest.mark.anyio
async def test_concurrent_approvals_share_one_saved_timestamp(db_session: AsyncSession) -> None:
    seeded = await seed_items(db_session, ("one", {}))
    service = build_service(db_session)

    results = await asyncio.gather(*(service.approve(seeded[0].id) for _ in range(5)))

    assert all(item.status == "saved" for item in results)
    assert results[0].saved_at is not None
    assert {item.saved_at for item in results} == {results[0].saved_at}


@pytest.mark.anyio
async def test_concurrent_approve_and_ignore_keep_one_terminal_state(db_session: AsyncSession) -> None:
    seeded = await seed_items(db_session, ("one", {}))
    service = build_service(db_session)

    results = await asyncio.gather(service.approve(seeded[0].id), service.ignore(seeded[0].id), return_exceptions=True)

    successes = [result for result in results if isinstance(result, RssItem)]
    errors = [result for result in results if isinstance(result, CandidateReviewError)]
    assert len(successes) == len(errors) == 1
    assert errors[0].status_code == 409
    await db_session.refresh(seeded[0])
    assert seeded[0].status == successes[0].status
    assert (seeded[0].saved_at is not None) == (seeded[0].status == "saved")


@pytest.mark.anyio
async def test_ignore_marks_candidate_ignored(db_session: AsyncSession) -> None:
    seeded = await seed_items(db_session, ("one", {}))
    service = build_service(db_session)

    ignored = await service.ignore(seeded[0].id)

    assert ignored.status == "ignored"
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    async with factory() as session:
        stored = await session.get(RssItem, seeded[0].id)
        assert stored is not None
        assert stored.status == "ignored"


@pytest.mark.anyio
async def test_ignore_missing_candidate_raises_not_found(db_session: AsyncSession) -> None:
    with pytest.raises(CandidateReviewError) as caught:
        await build_service(db_session).ignore(uuid4())

    assert caught.value.code == "RSS_CANDIDATE_NOT_FOUND"
    assert caught.value.status_code == 404


@pytest.mark.anyio
async def test_ignore_already_ignored_is_idempotent(db_session: AsyncSession) -> None:
    seeded = await seed_items(db_session, ("one", {"status": "ignored"}))

    result = await build_service(db_session).ignore(seeded[0].id)

    assert result.status == "ignored"


@pytest.mark.anyio
async def test_ignore_non_candidate_raises_conflict(db_session: AsyncSession) -> None:
    seeded = await seed_items(db_session, ("one", {"status": "saved"}))

    with pytest.raises(CandidateReviewError) as caught:
        await build_service(db_session).ignore(seeded[0].id)

    assert caught.value.code == "RSS_CANDIDATE_NOT_IGNORABLE"
    assert caught.value.status_code == 409


@pytest.mark.anyio
async def test_mark_review_pushed_updates_timestamp_in_one_transaction(db_session: AsyncSession) -> None:
    seeded = await seed_items(db_session, ("one", {}), ("two", {}))
    service = build_service(db_session)

    await service.mark_review_pushed([item.id for item in seeded])

    assert await service.list_pending_review() == []
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    async with factory() as session:
        for item in seeded:
            stored = await session.get(RssItem, item.id)
            assert stored is not None
            assert stored.review_pushed_at is not None


@pytest.mark.anyio
async def test_mark_review_pushed_with_empty_ids_is_noop(db_session: AsyncSession) -> None:
    seeded = await seed_items(db_session, ("one", {}))
    service = build_service(db_session)

    await service.mark_review_pushed([])

    assert [item.id for item in await service.list_pending_review()] == [seeded[0].id]
