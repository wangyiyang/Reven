import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from reven.articles.models import Article
from reven.jobs.repository import JobRepository
from reven.publishing.blog.store import SqlAlchemyBlogResultStore
from sqlalchemy.ext.asyncio import async_sessionmaker


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("branch", "reven/11111111-aaaaaaaaaaaa"),
        ("commit_sha", "a" * 40),
        ("pull_request_number", 7),
        ("merge_sha", "b" * 40),
        ("pages_build_id", 9),
        ("article_url", "https://www.wangyiyang.cc/2026/08/01/post/"),
    ],
)
async def test_blog_result_store_fences_stale_claim_at_every_phase(db_session, field: str, value: object) -> None:  # type: ignore[no-untyped-def]
    now = datetime.now(tz=UTC)
    article = Article(
        notion_page_id="11111111-1111-1111-1111-111111111111",
        notion_url="https://www.notion.so/11111111111111111111111111111111",
        title="测试稿件",
        notion_status="待发布",
        notion_last_edited_at=now,
        last_synced_at=now,
    )
    db_session.add(article)
    await db_session.flush()
    repository = JobRepository(db_session)
    await repository.create_waiting(
        article_id=article.id,
        content_hash="a" * 64,
        target_channels=["个人博客"],
        scheduled_at=now - timedelta(minutes=1),
    )
    await db_session.commit()
    claim = await repository.claim_next(lease_seconds=120)
    assert claim is not None
    await db_session.commit()
    store = SqlAlchemyBlogResultStore(async_sessionmaker(db_session.bind, expire_on_commit=False))

    assert await store.save_result(claim, {field: value})
    stale = type(claim)(claim.job_id, uuid4())
    assert not await store.save_result(stale, {field: "stale"})


@pytest.mark.anyio
async def test_begin_operation_has_single_database_winner(db_session) -> None:  # type: ignore[no-untyped-def]
    now = datetime.now(tz=UTC)
    article = Article(
        notion_page_id="22222222-2222-2222-2222-222222222222",
        notion_url="https://www.notion.so/22222222222222222222222222222222",
        title="竞争测试",
        notion_status="待发布",
        notion_last_edited_at=now,
        last_synced_at=now,
    )
    db_session.add(article)
    await db_session.flush()
    job = await JobRepository(db_session).create_waiting(
        article_id=article.id,
        content_hash="b" * 64,
        target_channels=["个人博客"],
        scheduled_at=now - timedelta(minutes=1),
    )
    await db_session.commit()
    claim = await JobRepository(db_session).claim_next(lease_seconds=120)
    assert claim is not None and claim.job_id == job.id
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    first, second = await asyncio.gather(
        SqlAlchemyBlogResultStore(factory).begin_operation_if_absent(claim, "merge"),
        SqlAlchemyBlogResultStore(factory).begin_operation_if_absent(claim, "merge"),
    )
    assert sum(value is not None for value in (first, second)) == 1
