import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

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

    async def execute(self, claim):  # type: ignore[no-untyped-def]
        del claim
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
async def test_preparation_heartbeat_prevents_second_claim_after_original_expiry(db_session) -> None:  # type: ignore[no-untyped-def]
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
    tick = PublicationJobTick(
        factory,
        BlockingPreparation(),
        executor=None,
        lease_seconds=1,
        heartbeat_seconds=0.05,
    )
    task = asyncio.create_task(tick())
    await started.wait()
    await asyncio.sleep(1.1)
    async with factory.begin() as session:
        second = await JobRepository(session).claim_next_preparation_pending(lease_seconds=1)

    assert second is None
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.anyio
async def test_lost_preparation_lease_cancels_worker_without_state_update(db_session) -> None:  # type: ignore[no-untyped-def]
    job = await _job(db_session)
    job.snapshot_metadata = {"notion_write_pending": True}
    original_schedule = job.scheduled_at
    await db_session.commit()
    started = asyncio.Event()
    cancelled = asyncio.Event()

    class BlockingPreparation:
        async def prepare(self, job_id):  # type: ignore[no-untyped-def]
            del job_id
            started.set()
            try:
                await asyncio.Future()
            finally:
                cancelled.set()

    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    tick = PublicationJobTick(
        factory,
        BlockingPreparation(),
        executor=None,
        heartbeat_seconds=0,
    )
    task = asyncio.create_task(tick())
    await started.wait()
    async with factory.begin() as session:
        current = await session.get(type(job), job.id)
        assert current is not None
        current.lease_token = uuid4()

    await task
    await db_session.refresh(job)

    assert cancelled.is_set()
    assert job.overall_status == JobStatus.WAITING
    assert job.scheduled_at == original_schedule
    assert "preparation_attempt_count" not in job.snapshot_metadata


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
    assert "preparation_attempt_count" not in job.snapshot_metadata
    assert job.snapshot_metadata["asset_finalize_pending"] is True


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
        async def execute(self, claim):  # type: ignore[no-untyped-def]
            calls.append(("execute", claim.job_id))

    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    await PublicationJobTick(factory, RecordingPreparation(), RecordingExecutor())()

    assert calls == [
        ("prepare", pending.id),
        ("prepare", executable.id),
        ("execute", executable.id),
    ]


@pytest.mark.anyio
async def test_regular_prepare_transient_uses_preparation_attempts_not_execution_attempt(db_session) -> None:  # type: ignore[no-untyped-def]
    job = await _job(db_session)
    job.snapshot_metadata = {"manifest": {"keep": True}}
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    preparation = RaisingPreparation(TransientPublishError("network"))
    executor = RaisingExecutor(AssertionError("must not execute"))
    tick = PublicationJobTick(factory, preparation, executor)

    for status in (JobStatus.WAITING, JobStatus.WAITING, JobStatus.FAILED):
        await tick()
        await db_session.refresh(job)
        assert job.overall_status == status
        assert job.attempt_count == 0
        assert job.snapshot_metadata["manifest"] == {"keep": True}
        if status == JobStatus.WAITING:
            job.scheduled_at = utc_now() - timedelta(seconds=1)
            await db_session.commit()

    assert preparation.calls == 3
    assert executor.calls == 0
    assert "preparation_attempt_count" not in job.snapshot_metadata


@pytest.mark.anyio
async def test_blocked_after_transient_preparation_clears_retry_cycle(db_session) -> None:  # type: ignore[no-untyped-def]
    job = await _job(db_session)
    job.snapshot_metadata = {
        "asset_finalize_pending": True,
        "asset_manifest": [{"name": "cover.png", "sha256": "a" * 64}],
    }
    await db_session.commit()
    outcomes = [
        TransientPublishError("network"),
        TransientPublishError("network"),
        PrepareResult(job.id, blocked=True),
    ]

    class SequencedPreparation:
        async def prepare(self, job_id):  # type: ignore[no-untyped-def]
            del job_id
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    tick = PublicationJobTick(factory, SequencedPreparation(), executor=None)
    for _ in range(3):
        await tick()
        await db_session.refresh(job)
        if job.overall_status == JobStatus.WAITING:
            job.scheduled_at = utc_now() - timedelta(seconds=1)
            await db_session.commit()

    assert job.overall_status == JobStatus.BLOCKED
    assert "preparation_attempt_count" not in job.snapshot_metadata
    assert job.snapshot_metadata["asset_finalize_pending"] is True
    assert job.snapshot_metadata["asset_manifest"][0]["name"] == "cover.png"

    job.overall_status = JobStatus.WAITING
    job.scheduled_at = utc_now() - timedelta(seconds=1)
    await db_session.commit()
    repaired_tick = PublicationJobTick(
        factory,
        RaisingPreparation(TransientPublishError("new network failure")),
        executor=None,
    )
    await repaired_tick()
    await db_session.refresh(job)

    assert job.overall_status == JobStatus.WAITING
    assert job.snapshot_metadata["preparation_attempt_count"] == 1


@pytest.mark.anyio
async def test_terminal_finalization_bypasses_content_preparation(db_session) -> None:  # type: ignore[no-untyped-def]
    job = await _job(db_session)
    job.overall_status = JobStatus.COMPLETED
    job.snapshot_metadata = {
        "delivery_finalization": {
            "final_status": JobStatus.COMPLETED,
            "notion_pending": False,
            "cleanup_pending": True,
        }
    }
    await db_session.commit()
    preparation = RaisingPreparation(AssertionError("must not prepare"))

    class RecordingExecutor:
        def __init__(self) -> None:
            self.calls = 0

        async def execute(self, claim):  # type: ignore[no-untyped-def]
            del claim
            self.calls += 1

    executor = RecordingExecutor()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    await PublicationJobTick(factory, preparation, executor)()

    assert preparation.calls == 0
    assert executor.calls == 1


@pytest.mark.anyio
async def test_exhausted_notion_finalization_is_not_hot_loop_claimed(db_session) -> None:  # type: ignore[no-untyped-def]
    job = await _job(db_session)
    job.snapshot_metadata = {
        "delivery_finalization": {
            "final_status": JobStatus.COMPLETED,
            "notion_pending": True,
            "cleanup_pending": False,
        }
    }
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    preparation = RaisingPreparation(AssertionError("must not prepare"))
    executor = RaisingExecutor(TransientPublishError("Notion unavailable"))
    tick = PublicationJobTick(factory, preparation, executor)

    for expected_attempt in (1, 2, 3):
        await tick()
        await db_session.refresh(job)
        assert job.attempt_count == expected_attempt
        if expected_attempt < 3:
            job.scheduled_at = utc_now() - timedelta(seconds=1)
            await db_session.commit()

    assert job.overall_status == JobStatus.FAILED
    await tick()
    await db_session.refresh(job)
    assert job.attempt_count == 3
    assert executor.calls == 3
    assert preparation.calls == 0
