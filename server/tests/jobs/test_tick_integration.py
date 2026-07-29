import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from reven.articles.models import Article
from reven.domain import JobStatus
from reven.jobs.errors import BlockedPublishError, PermanentPublishError, TransientPublishError
from reven.jobs.preparation_models import PrepareResult
from reven.jobs.repository import JobRepository
from reven.jobs.runner import PublicationJobTick
from reven.scheduling import utc_now
from sqlalchemy.ext.asyncio import async_sessionmaker


class ReadyPreparation:
    async def prepare(self, job_id):  # type: ignore[no-untyped-def]
        del job_id


class RaisingExecutor:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0

    async def execute(self, job_id):  # type: ignore[no-untyped-def]
        del job_id
        self.calls += 1
        raise self.error


class RaisingPreparation:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0

    async def prepare(self, job_id):  # type: ignore[no-untyped-def]
        del job_id
        self.calls += 1
        raise self.error


async def _job(db_session):  # type: ignore[no-untyped-def]
    now = utc_now()
    article = Article(
        notion_page_id="11111111-1111-1111-1111-111111111111",
        notion_url="https://www.notion.so/test",
        title="测试",
        notion_status="待发布",
        automation_status="等待中",
        notion_last_edited_at=now,
        last_synced_at=now,
    )
    db_session.add(article)
    await db_session.flush()
    job = await JobRepository(db_session).create_waiting(
        article_id=article.id,
        content_hash="a" * 64,
        target_channels=["个人博客"],
        scheduled_at=now - timedelta(seconds=1),
    )
    await db_session.commit()
    return job


@pytest.mark.anyio
async def test_transient_execution_uses_real_attempt_for_30_120_then_failed(db_session) -> None:  # type: ignore[no-untyped-def]
    job = await _job(db_session)
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    executor = RaisingExecutor(TransientPublishError("timeout"))
    tick = PublicationJobTick(factory, ReadyPreparation(), executor)

    for expected_attempt, expected_status in (
        (1, JobStatus.WAITING),
        (2, JobStatus.WAITING),
        (3, JobStatus.FAILED),
    ):
        await tick()
        await db_session.refresh(job)
        assert job.attempt_count == expected_attempt
        assert job.overall_status == expected_status
        if expected_attempt < 3:
            assert job.scheduled_at > datetime.now(tz=UTC)
            job.scheduled_at = utc_now() - timedelta(seconds=1)
            await db_session.commit()

    await tick()
    assert executor.calls == 3


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("error", "status"),
    [
        (BlockedPublishError("缺少封面"), JobStatus.BLOCKED),
        (PermanentPublishError("拒绝"), JobStatus.FAILED),
        (RuntimeError("bug"), JobStatus.FAILED),
    ],
)
async def test_execution_error_category_sets_terminal_status(db_session, error, status) -> None:  # type: ignore[no-untyped-def]
    job = await _job(db_session)
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    await PublicationJobTick(factory, ReadyPreparation(), RaisingExecutor(error))()
    await db_session.refresh(job)

    assert job.overall_status == status


@pytest.mark.anyio
async def test_cancelled_preparation_releases_lease_immediately(db_session) -> None:  # type: ignore[no-untyped-def]
    job = await _job(db_session)
    job.snapshot_metadata = {"notion_write_pending": True}
    await db_session.commit()
    started = asyncio.Event()

    class BlockingPreparation:
        async def prepare(self, job_id):  # type: ignore[no-untyped-def]
            del job_id
            started.set()
            await asyncio.Future()

    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    task = asyncio.create_task(PublicationJobTick(factory, BlockingPreparation(), executor=None)())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await db_session.refresh(job)

    assert job.lease_token is None
    assert job.lease_expires_at is None


@pytest.mark.anyio
async def test_transient_preparation_retries_without_execution_attempt(db_session) -> None:  # type: ignore[no-untyped-def]
    job = await _job(db_session)
    job.snapshot_metadata = {"asset_finalize_pending": True}
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    preparation = RaisingPreparation(TransientPublishError("network"))
    tick = PublicationJobTick(factory, preparation, executor=None)

    for expected_status in (JobStatus.WAITING, JobStatus.WAITING, JobStatus.FAILED):
        await tick()
        await db_session.refresh(job)
        assert job.attempt_count == 0
        assert job.overall_status == expected_status
        if expected_status == JobStatus.WAITING:
            job.scheduled_at = utc_now() - timedelta(seconds=1)
            await db_session.commit()

    assert preparation.calls == 3
    assert job.snapshot_metadata["preparation_attempt_count"] == 3


@pytest.mark.anyio
async def test_blocked_prepare_result_never_calls_executor(db_session) -> None:  # type: ignore[no-untyped-def]
    job = await _job(db_session)
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    executor = RaisingExecutor(AssertionError("must not execute"))

    class BlockedPreparation:
        async def prepare(self, job_id):  # type: ignore[no-untyped-def]
            return PrepareResult(job_id, blocked=True)

    await PublicationJobTick(factory, BlockedPreparation(), executor)()
    await db_session.refresh(job)

    assert executor.calls == 0
    assert job.attempt_count == 0
    assert job.overall_status == JobStatus.BLOCKED


@pytest.mark.anyio
async def test_pending_preparation_runs_first_and_is_never_executed(db_session) -> None:  # type: ignore[no-untyped-def]
    pending = await _job(db_session)
    pending.snapshot_metadata = {"notion_write_pending": True}
    now = utc_now()
    article = Article(
        notion_page_id="22222222-2222-2222-2222-222222222222",
        notion_url="https://www.notion.so/second",
        title="第二篇",
        notion_status="待发布",
        automation_status="等待中",
        notion_last_edited_at=now,
        last_synced_at=now,
    )
    db_session.add(article)
    await db_session.flush()
    executable = await JobRepository(db_session).create_waiting(
        article_id=article.id,
        content_hash="b" * 64,
        target_channels=["个人博客"],
        scheduled_at=now - timedelta(seconds=1),
    )
    await db_session.commit()
    calls: list[tuple[str, object]] = []

    class RecordingPreparation:
        async def prepare(self, job_id):  # type: ignore[no-untyped-def]
            calls.append(("prepare", job_id))

    class RecordingExecutor:
        async def execute(self, job_id):  # type: ignore[no-untyped-def]
            calls.append(("execute", job_id))

    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    await PublicationJobTick(factory, RecordingPreparation(), RecordingExecutor())()

    assert calls == [
        ("prepare", pending.id),
        ("prepare", executable.id),
        ("execute", executable.id),
    ]
