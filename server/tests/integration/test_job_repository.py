import asyncio
import os
from datetime import UTC, datetime, timedelta

import pytest
from reven.articles.models import Article
from reven.domain import JobStatus
from reven.jobs.repository import JobClaim, JobRepository
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def _new_article() -> Article:
    now = datetime.now(tz=UTC)
    return Article(
        notion_page_id="11111111-1111-1111-1111-111111111111",
        notion_url="https://www.notion.so/11111111111111111111111111111111",
        title="测试稿件",
        notion_status="待发布",
        automation_status="等待中",
        notion_last_edited_at=now,
        last_synced_at=now,
    )


@pytest.mark.anyio
async def test_claim_due_job_sets_processing_lease(db_session) -> None:  # type: ignore[no-untyped-def]
    article = _new_article()
    db_session.add(article)
    await db_session.flush()
    repository = JobRepository(db_session)
    job = await repository.create_waiting(
        article_id=article.id,
        content_hash="a" * 64,
        target_channels=["个人博客"],
        scheduled_at=datetime.now(tz=UTC) - timedelta(minutes=1),
    )
    await db_session.commit()

    claimed = await repository.claim_next(lease_seconds=120)

    assert claimed is not None
    assert claimed.job_id == job.id
    await db_session.refresh(job)
    assert job.overall_status == JobStatus.PROCESSING
    assert job.lease_expires_at is not None
    assert job.lease_token == claimed.lease_token


@pytest.mark.anyio
async def test_concurrent_claimants_cannot_take_same_job(db_session) -> None:  # type: ignore[no-untyped-def]
    article = _new_article()
    db_session.add(article)
    await db_session.flush()
    repository = JobRepository(db_session)
    job = await repository.create_waiting(
        article_id=article.id,
        content_hash=None,
        target_channels=["个人博客"],
        scheduled_at=datetime.now(tz=UTC) - timedelta(minutes=1),
    )
    await db_session.commit()

    database_url = os.environ["TEST_DATABASE_URL"]

    async def claim() -> JobClaim | None:
        engine = create_async_engine(database_url)
        try:
            session_factory = async_sessionmaker(engine, expire_on_commit=False)
            async with session_factory() as session:
                claimed = await JobRepository(session).claim_next(lease_seconds=120)
                await session.commit()
                return claimed
        finally:
            await engine.dispose()

    first, second = await asyncio.gather(claim(), claim())

    winners = [claimed.job_id for claimed in (first, second) if claimed is not None]
    assert winners == [job.id]


@pytest.mark.anyio
@pytest.mark.parametrize("pending_flag", ["notion_write_pending", "asset_finalize_pending"])
async def test_pending_preparation_uses_recovery_queue_not_execution_queue(db_session, pending_flag: str) -> None:  # type: ignore[no-untyped-def]
    article = _new_article()
    db_session.add(article)
    await db_session.flush()
    repository = JobRepository(db_session)
    job = await repository.create_waiting(
        article_id=article.id,
        content_hash="a" * 64,
        target_channels=["个人博客"],
        scheduled_at=datetime.now(tz=UTC) - timedelta(minutes=1),
    )
    job.snapshot_metadata = {pending_flag: True}
    await db_session.commit()

    assert await repository.claim_next(lease_seconds=120) is None
    preparation = await repository.claim_next_preparation_pending(lease_seconds=120)
    assert preparation is not None
    assert preparation.job_id == job.id
    await db_session.refresh(job)
    assert job.overall_status == JobStatus.WAITING

    job.snapshot_metadata = {}
    assert await repository.release_lease(preparation) is True
    await db_session.commit()
    executable = await repository.claim_next(lease_seconds=120)
    assert executable is not None
    assert executable.job_id == job.id


@pytest.mark.anyio
async def test_old_lease_token_cannot_renew_or_release_new_lease(db_session) -> None:  # type: ignore[no-untyped-def]
    article = _new_article()
    db_session.add(article)
    await db_session.flush()
    repository = JobRepository(db_session)
    await repository.create_waiting(
        article_id=article.id,
        content_hash="b" * 64,
        target_channels=["个人博客"],
        scheduled_at=datetime.now(tz=UTC) - timedelta(minutes=1),
    )
    await db_session.commit()
    first = await repository.claim_next(lease_seconds=-1)
    await db_session.commit()
    second = await repository.claim_next(lease_seconds=120)
    await db_session.commit()
    assert first is not None and second is not None

    assert await repository.renew_lease(first, lease_seconds=120) is False
    assert await repository.release_lease(first) is False
    assert await repository.renew_lease(second, lease_seconds=120) is True


@pytest.mark.anyio
async def test_blocked_preparation_is_not_hot_loop_claimed(db_session) -> None:  # type: ignore[no-untyped-def]
    article = _new_article()
    db_session.add(article)
    await db_session.flush()
    repository = JobRepository(db_session)
    job = await repository.create_waiting(
        article_id=article.id,
        content_hash="c" * 64,
        target_channels=["个人博客"],
        scheduled_at=datetime.now(tz=UTC) - timedelta(minutes=1),
    )
    job.snapshot_metadata = {"asset_finalize_pending": True}
    job.overall_status = JobStatus.BLOCKED
    await db_session.commit()

    assert await repository.claim_next_preparation_pending(lease_seconds=120) is None
