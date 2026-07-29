import asyncio

import pytest
from fastapi import HTTPException
from reven.jobs.errors import TransientPublishError
from reven.jobs.runner import (
    BackgroundRunner,
    ConfiguredNotionSyncTick,
    PublicationJobTick,
    run_until_heartbeat_stops,
)
from reven.publishing.assets import AssetDownloadError


class FakeJobLoop:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self) -> None:
        self.calls += 1


@pytest.mark.anyio
async def test_runner_stop_cancels_and_awaits_all_background_tasks() -> None:
    sync = FakeJobLoop()
    jobs = FakeJobLoop()
    runner = BackgroundRunner(sync, jobs, sync_interval=3600, job_interval=3600)

    await runner.start()
    tasks = runner.tasks
    await asyncio.sleep(0)
    await runner.stop()

    assert len(tasks) == 2
    assert all(task.done() and task.cancelled() for task in tasks)
    assert runner.tasks == ()


@pytest.mark.anyio
async def test_loop_isolates_tick_failures_and_keeps_running() -> None:
    calls = 0
    second_call = asyncio.Event()

    async def failing_once() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("external response")
        second_call.set()

    runner = BackgroundRunner(failing_once, FakeJobLoop(), sync_interval=0, job_interval=3600)
    await runner.start()
    await asyncio.wait_for(second_call.wait(), timeout=1)
    await runner.stop()

    assert calls >= 2


@pytest.mark.anyio
async def test_cancelled_error_from_tick_stops_loop() -> None:
    started = asyncio.Event()

    async def cancelled_tick() -> None:
        started.set()
        raise asyncio.CancelledError

    runner = BackgroundRunner(cancelled_tick, FakeJobLoop(), sync_interval=0, job_interval=3600)
    await runner.start()
    await started.wait()
    await asyncio.sleep(0)

    sync_task = runner.tasks[0]
    assert sync_task.cancelled()
    await runner.stop()


@pytest.mark.anyio
async def test_lost_lease_cancels_and_awaits_execution() -> None:
    execution_cancelled = asyncio.Event()

    async def execute() -> None:
        try:
            await asyncio.Future()
        finally:
            execution_cancelled.set()

    async def lost_lease() -> None:
        await asyncio.sleep(0)
        raise TransientPublishError("租约丢失")

    with pytest.raises(TransientPublishError):
        await run_until_heartbeat_stops(execute(), lost_lease())

    assert execution_cancelled.is_set()


def test_asset_finalize_integrity_error_is_blocked() -> None:
    error = AssetDownloadError("asset_finalize_mismatch", "tampered", field="assets")

    classified = PublicationJobTick._publish_error(error)

    assert type(classified).__name__ == "BlockedPublishError"


def test_asset_finalize_os_error_is_transient() -> None:
    try:
        raise OSError("disk busy")
    except OSError as cause:
        error = AssetDownloadError("asset_finalize_failed", "failed", field="assets")
        error.__cause__ = cause

    assert isinstance(PublicationJobTick._publish_error(error), TransientPublishError)


@pytest.mark.anyio
async def test_configured_sync_tick_skips_missing_integration(monkeypatch) -> None:
    async def missing(factory):  # type: ignore[no-untyped-def]
        del factory
        raise HTTPException(status_code=409, detail="not configured")

    monkeypatch.setattr("reven.jobs.runner._load_notion_config", missing)

    await ConfiguredNotionSyncTick(object())()  # type: ignore[arg-type]
