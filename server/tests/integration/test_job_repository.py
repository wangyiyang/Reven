import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from reven.articles.models import Article
from reven.domain import JobStatus
from reven.jobs.errors import BlockedPublishError, TransientPublishError
from reven.jobs.models import PublicationJob
from reven.jobs.repository import JobClaim, JobRepository
from sqlalchemy import select, text
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
    assert first is not None
    assert await repository.renew_lease(first, lease_seconds=120) is False
    second = await repository.claim_next(lease_seconds=120)
    await db_session.commit()
    assert first is not None and second is not None

    assert await repository.renew_lease(first, lease_seconds=120) is False
    assert await repository.release_lease(first) is False
    assert await repository.renew_lease(second, lease_seconds=120) is True


@pytest.mark.anyio
async def test_stale_claim_cannot_persist_terminal_status(db_session) -> None:  # type: ignore[no-untyped-def]
    article = _new_article()
    db_session.add(article)
    await db_session.flush()
    repository = JobRepository(db_session)
    job = await repository.create_waiting(
        article_id=article.id,
        content_hash="d" * 64,
        target_channels=["个人博客"],
        scheduled_at=datetime.now(tz=UTC) - timedelta(minutes=1),
    )
    await db_session.commit()
    stale = await repository.claim_next(lease_seconds=-1)
    await db_session.commit()
    current = await repository.claim_next(lease_seconds=120)
    await db_session.commit()
    assert stale is not None and current is not None

    assert await repository.mark_completed_if_leased(stale) is False
    assert await repository.mark_completed_if_leased(current) is True
    await db_session.commit()
    await db_session.refresh(job)

    assert job.overall_status == JobStatus.COMPLETED
    assert job.finished_at is not None
    assert job.lease_token is None
    assert job.lease_expires_at is None


@pytest.mark.anyio
async def test_renew_lease_uses_database_clock(db_session) -> None:  # type: ignore[no-untyped-def]
    article = _new_article()
    db_session.add(article)
    await db_session.flush()
    repository = JobRepository(db_session)
    job = await repository.create_waiting(
        article_id=article.id,
        content_hash="e" * 64,
        target_channels=["个人博客"],
        scheduled_at=datetime.now(tz=UTC) - timedelta(minutes=1),
    )
    await db_session.commit()
    claim = await repository.claim_next(lease_seconds=120)
    assert claim is not None
    await db_session.execute(
        text(
            "UPDATE publication_jobs SET lease_expires_at = CURRENT_TIMESTAMP - INTERVAL '1 second' WHERE id = :job_id"
        ),
        {"job_id": job.id},
    )
    await db_session.commit()

    assert await repository.renew_lease(claim, lease_seconds=120) is False


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


@pytest.mark.anyio
async def test_terminal_finalization_is_reclaimable_without_changing_terminal_status(
    db_session,
) -> None:  # type: ignore[no-untyped-def]
    article = _new_article()
    db_session.add(article)
    await db_session.flush()
    repository = JobRepository(db_session)
    job = await repository.create_waiting(
        article_id=article.id,
        content_hash="f" * 64,
        target_channels=["个人博客"],
        scheduled_at=datetime.now(tz=UTC) - timedelta(minutes=1),
    )
    job.overall_status = JobStatus.COMPLETED
    job.snapshot_metadata = {
        "delivery_finalization": {
            "final_status": JobStatus.COMPLETED,
            "notion_pending": False,
            "cleanup_pending": True,
        }
    }
    await db_session.commit()

    claim = await repository.claim_next(lease_seconds=120)
    await db_session.commit()

    assert claim is not None
    await db_session.refresh(job)
    assert job.overall_status == JobStatus.COMPLETED
    assert await repository.is_finalization_pending(claim)
    assert await repository.begin_execution(claim) == 1
    assert (
        await repository.mark_retry(
            claim,
            delay_seconds=30,
            error=TransientPublishError("cleanup"),
        )
        is False
    )
    await db_session.refresh(job)
    assert job.overall_status == JobStatus.COMPLETED


@pytest.mark.anyio
@pytest.mark.parametrize("status", [JobStatus.BLOCKED, JobStatus.FAILED])
async def test_notion_pending_terminal_job_requires_manual_retry(
    db_session,
    status: JobStatus,
) -> None:  # type: ignore[no-untyped-def]
    article = _new_article()
    db_session.add(article)
    await db_session.flush()
    repository = JobRepository(db_session)
    job = await repository.create_waiting(
        article_id=article.id,
        content_hash="2" * 64,
        target_channels=["个人博客"],
        scheduled_at=datetime.now(tz=UTC) - timedelta(minutes=1),
    )
    job.overall_status = status
    job.snapshot_metadata = {
        "delivery_finalization": {
            "final_status": status,
            "notion_pending": True,
            "cleanup_pending": False,
        }
    }
    await db_session.commit()

    assert await repository.claim_next(lease_seconds=120) is None
    assert await repository.bump_notification_revision_for_retry(job.id) == 1
    await db_session.commit()

    claim = await repository.claim_next(lease_seconds=120)
    assert claim is not None
    assert claim.job_id == job.id


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("error", "delay", "job_status", "article_status"),
    [
        (BlockedPublishError("token=must-not-leak"), None, JobStatus.BLOCKED, "阻塞"),
        (TransientPublishError("token=must-not-leak"), None, JobStatus.FAILED, "失败"),
    ],
)
async def test_notion_terminal_failure_updates_article_with_safe_error(
    db_session,
    error,
    delay,
    job_status: JobStatus,
    article_status: str,
) -> None:  # type: ignore[no-untyped-def]
    article = _new_article()
    db_session.add(article)
    await db_session.flush()
    repository = JobRepository(db_session)
    job = await repository.create_waiting(
        article_id=article.id,
        content_hash="3" * 64,
        target_channels=["个人博客"],
        scheduled_at=datetime.now(tz=UTC) - timedelta(seconds=1),
    )
    job.snapshot_metadata = {
        "delivery_finalization": {
            "final_status": JobStatus.COMPLETED,
            "notion_pending": True,
            "cleanup_pending": False,
        }
    }
    await db_session.commit()
    claim = await repository.claim_next(lease_seconds=120)
    assert claim is not None

    stale = JobClaim(job.id, uuid4())
    assert await repository.mark_retry(stale, delay_seconds=delay, error=error) is False
    assert article.automation_status == "等待中"
    assert await repository.mark_retry(claim, delay_seconds=delay, error=error)
    await db_session.commit()
    await db_session.refresh(job)
    await db_session.refresh(article)

    assert job.overall_status == job_status
    assert article.automation_status == article_status
    assert article.last_error is not None
    assert "must-not-leak" not in article.last_error


@pytest.mark.anyio
async def test_manual_retry_revision_is_database_clock_fenced(db_session) -> None:  # type: ignore[no-untyped-def]
    article = _new_article()
    db_session.add(article)
    await db_session.flush()
    repository = JobRepository(db_session)
    job = await repository.create_waiting(
        article_id=article.id,
        content_hash="1" * 64,
        target_channels=["个人博客"],
        scheduled_at=datetime.now(tz=UTC) - timedelta(seconds=1),
    )
    job.snapshot_metadata = {
        "delivery_finalization": {
            "final_status": JobStatus.COMPLETED,
            "notion_pending": True,
            "cleanup_pending": False,
        }
    }
    await db_session.commit()
    claim = await repository.claim_next(lease_seconds=120)
    await db_session.commit()
    assert claim is not None

    article.automation_status = "阻塞"
    article.last_error = "old"
    await db_session.commit()
    assert await repository.bump_notification_revision_for_retry(job.id) is None
    await db_session.execute(
        text(
            "UPDATE publication_jobs "
            "SET lease_expires_at = clock_timestamp() - INTERVAL '1 second', "
            "overall_status = '失败' WHERE id = :job_id"
        ),
        {"job_id": job.id},
    )
    await db_session.commit()

    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    async def bump() -> int | None:
        async with factory.begin() as session:
            return await JobRepository(session).bump_notification_revision_for_retry(job.id)

    revisions = await asyncio.gather(bump(), bump())

    assert sorted(value for value in revisions if value is not None) == [1, 2]
    await db_session.refresh(job)
    await db_session.refresh(article)
    assert job.notification_state["_revision"] == 2
    assert article.automation_status == "等待中"
    assert article.last_error is None


async def _sync_article_then_job(
    factory,
    article_id,
    job_id,
    article_locked: asyncio.Event,
    retry_started: asyncio.Event,
    *,
    increment_revision: bool,
) -> None:  # type: ignore[no-untyped-def]
    async with factory.begin() as session:
        article = await session.scalar(select(Article).where(Article.id == article_id).with_for_update())
        assert article is not None
        article.title = "同步后的标题"
        article_locked.set()
        await retry_started.wait()
        job = await session.scalar(select(PublicationJob).where(PublicationJob.id == job_id).with_for_update())
        assert job is not None
        if increment_revision:
            job.notification_state = {**job.notification_state, "_revision": 1}


def _signal_lock_attempt(
    repository: JobRepository,
    retry_started: asyncio.Event,
) -> None:
    original = repository._lock_article_then_job

    async def wrapped(job_id):  # type: ignore[no-untyped-def]
        retry_started.set()
        return await original(job_id)

    repository._lock_article_then_job = wrapped  # type: ignore[method-assign]


@pytest.mark.anyio
async def test_notion_sync_and_mark_retry_follow_article_job_lock_order(
    db_session,
) -> None:  # type: ignore[no-untyped-def]
    article = _new_article()
    db_session.add(article)
    await db_session.flush()
    job = await JobRepository(db_session).create_waiting(
        article_id=article.id,
        content_hash="4" * 64,
        target_channels=["个人博客"],
        scheduled_at=datetime.now(tz=UTC) - timedelta(seconds=1),
    )
    job.snapshot_metadata = {
        "delivery_finalization": {
            "final_status": JobStatus.COMPLETED,
            "notion_pending": True,
        }
    }
    await db_session.commit()
    claim = await JobRepository(db_session).claim_next(lease_seconds=120)
    await db_session.commit()
    assert claim is not None
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    article_locked, retry_started = asyncio.Event(), asyncio.Event()

    async def retry() -> None:
        await article_locked.wait()
        async with factory.begin() as session:
            repository = JobRepository(session)
            _signal_lock_attempt(repository, retry_started)
            assert await repository.mark_retry(
                claim,
                delay_seconds=None,
                error=BlockedPublishError("blocked"),
            )

    async with asyncio.timeout(3):
        await asyncio.gather(
            _sync_article_then_job(
                factory,
                article.id,
                job.id,
                article_locked,
                retry_started,
                increment_revision=False,
            ),
            retry(),
        )

    await db_session.refresh(article)
    await db_session.refresh(job)
    assert article.title == "同步后的标题"
    assert article.automation_status == "阻塞"
    assert job.overall_status == JobStatus.BLOCKED


@pytest.mark.anyio
async def test_notion_sync_and_manual_retry_do_not_deadlock_or_lose_revision(
    db_session,
) -> None:  # type: ignore[no-untyped-def]
    article = _new_article()
    db_session.add(article)
    await db_session.flush()
    job = await JobRepository(db_session).create_waiting(
        article_id=article.id,
        content_hash="5" * 64,
        target_channels=["个人博客"],
        scheduled_at=datetime.now(tz=UTC) - timedelta(seconds=1),
    )
    job.overall_status = JobStatus.BLOCKED
    job.snapshot_metadata = {
        "delivery_finalization": {
            "final_status": JobStatus.COMPLETED,
            "notion_pending": True,
        }
    }
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    article_locked, retry_started = asyncio.Event(), asyncio.Event()

    async def retry() -> None:
        await article_locked.wait()
        async with factory.begin() as session:
            repository = JobRepository(session)
            _signal_lock_attempt(repository, retry_started)
            assert await repository.bump_notification_revision_for_retry(job.id) == 2

    async with asyncio.timeout(3):
        await asyncio.gather(
            _sync_article_then_job(
                factory,
                article.id,
                job.id,
                article_locked,
                retry_started,
                increment_revision=True,
            ),
            retry(),
        )

    await db_session.refresh(article)
    await db_session.refresh(job)
    assert article.title == "同步后的标题"
    assert article.automation_status == "等待中"
    assert job.notification_state["_revision"] == 2
    assert job.overall_status == JobStatus.WAITING
