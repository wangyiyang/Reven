import asyncio

import pytest
from pydantic import ValidationError
from reven.config import Settings
from reven.integrations.notion.configuration import IntegrationConfigurationError
from reven.jobs.errors import TransientPublishError
from reven.jobs.runner import (
    BackgroundRunner,
    ConfiguredNotionSyncTick,
    PublicationJobTick,
    build_background_runner,
    heartbeat_interval_seconds,
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
async def test_loop_log_does_not_include_exception_secret(caplog) -> None:
    completed = asyncio.Event()
    calls = 0

    async def leaking_tick() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("token=super-secret https://cdn.example/a?X-Amz-Signature=signed-secret")
        completed.set()

    runner = BackgroundRunner(leaking_tick, FakeJobLoop(), sync_interval=0, job_interval=3600)
    await runner.start()
    await asyncio.wait_for(completed.wait(), timeout=1)
    await runner.stop()

    logs = caplog.text
    assert "super-secret" not in logs
    assert "signed-secret" not in logs
    assert "RuntimeError" in logs


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


@pytest.mark.anyio
async def test_parent_cancellation_cancels_and_awaits_both_children() -> None:
    execution_cancelled = asyncio.Event()
    heartbeat_cancelled = asyncio.Event()
    baseline = asyncio.all_tasks()

    async def endless(cancelled: asyncio.Event) -> None:
        try:
            await asyncio.Future()
        finally:
            cancelled.set()

    parent = asyncio.create_task(
        run_until_heartbeat_stops(
            endless(execution_cancelled),
            endless(heartbeat_cancelled),
        )
    )
    await asyncio.sleep(0)
    children = asyncio.all_tasks() - baseline - {parent}

    parent.cancel()
    with pytest.raises(asyncio.CancelledError):
        await parent

    assert execution_cancelled.is_set()
    assert heartbeat_cancelled.is_set()
    assert children
    assert all(task.done() for task in children)
    assert not (children & asyncio.all_tasks())


@pytest.mark.anyio
async def test_background_runner_stop_cleans_tick_children() -> None:
    execution_cancelled = asyncio.Event()
    heartbeat_cancelled = asyncio.Event()
    started = asyncio.Event()

    async def endless(cancelled: asyncio.Event) -> None:
        try:
            started.set()
            await asyncio.Future()
        finally:
            cancelled.set()

    async def sync_tick() -> None:
        await run_until_heartbeat_stops(
            endless(execution_cancelled),
            endless(heartbeat_cancelled),
        )

    runner = BackgroundRunner(sync_tick, FakeJobLoop(), sync_interval=3600, job_interval=3600)
    await runner.start()
    await started.wait()
    await runner.stop()

    assert execution_cancelled.is_set()
    assert heartbeat_cancelled.is_set()


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
        raise IntegrationConfigurationError("NOTION_SECRET_NOT_CONFIGURED")

    monkeypatch.setattr("reven.jobs.runner.load_notion_config", missing)

    await ConfiguredNotionSyncTick(object())()  # type: ignore[arg-type]


def test_default_runner_injects_delivery_orchestrator(monkeypatch) -> None:
    class Settings:
        job_lease_seconds = 120
        sync_interval_seconds = 60
        scheduler_interval_seconds = 5
        job_data_dir = "/tmp/reven-tests"
        public_base_url = "https://dev.example.com"
        renderer_command = "node /app/renderer/dist/cli.mjs"
        reven_master_key = type("Secret", (), {"get_secret_value": lambda self: "key"})()

    monkeypatch.setattr("reven.jobs.runner.get_settings", Settings)
    executor = object()
    monkeypatch.setattr(
        "reven.jobs.runner.build_configured_orchestrator",
        lambda factory, settings: executor,
    )
    runner = build_background_runner(object())  # type: ignore[arg-type]

    assert isinstance(runner._job_tick, PublicationJobTick)
    assert runner._job_tick._executor is executor


@pytest.mark.parametrize(
    ("lease_seconds", "expected"),
    [(3, 1), (30, 10), (31, 31 / 3), (120, 30)],
)
def test_heartbeat_interval_is_derived_before_lease_expiry(lease_seconds: int, expected: float) -> None:
    interval = heartbeat_interval_seconds(lease_seconds)

    assert interval == expected
    assert 0 < interval < lease_seconds


@pytest.mark.parametrize("lease_seconds", [0, -1, 1, 2])
def test_settings_reject_unsafe_job_lease(lease_seconds: int) -> None:
    with pytest.raises(ValidationError):
        Settings(
            database_url="postgresql+asyncpg://user:pass@localhost/reven",
            reven_master_key="test",
            job_lease_seconds=lease_seconds,
        )
