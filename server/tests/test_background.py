import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from reven.background import BackgroundRunner, RssDiscoveryTick, build_background_runner
from reven.system.models import SystemState
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.mark.anyio
async def test_runner_starts_only_rss_once_and_stop_awaits_cancellation() -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def tick() -> None:
        started.set()
        try:
            await asyncio.Future()
        finally:
            cancelled.set()

    runner = BackgroundRunner(tick)
    await runner.start()
    tasks = runner.tasks
    await runner.start()
    await started.wait()
    assert runner.tasks == tasks
    assert [task.get_name() for task in tasks] == ["reven-rss-discovery"]

    await runner.stop()

    assert cancelled.is_set()
    assert all(task.done() and task.cancelled() for task in tasks)
    assert runner.tasks == ()
    await runner.stop()


@pytest.mark.anyio
async def test_loop_recovers_tick_failures_without_logging_secrets(caplog) -> None:
    calls = 0
    recovered = asyncio.Event()

    async def tick() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("token=super-secret https://cdn.example?signature=signed-secret")
        recovered.set()

    runner = BackgroundRunner(tick, rss_interval=0)
    await runner.start()
    try:
        await asyncio.wait_for(recovered.wait(), timeout=1)
    finally:
        await runner.stop()

    assert calls >= 2
    assert "RuntimeError" in caplog.text
    assert "super-secret" not in caplog.text
    assert "signed-secret" not in caplog.text


@pytest.mark.anyio
async def test_tick_cancellation_stops_the_loop() -> None:
    started = asyncio.Event()

    async def tick() -> None:
        started.set()
        raise asyncio.CancelledError

    runner = BackgroundRunner(tick, rss_interval=0)
    await runner.start()
    await started.wait()
    await asyncio.sleep(0)

    assert runner.tasks[0].cancelled()
    await runner.stop()


def test_default_runner_builds_rss_with_notification_service() -> None:
    factory = object()
    clients = SimpleNamespace(credentials=object())
    settings = type("Settings", (), {"rss_scheduler_interval_seconds": 42})()

    runner = build_background_runner(factory, clients, settings)  # type: ignore[arg-type]

    assert isinstance(runner._rss_tick, RssDiscoveryTick)
    assert runner._rss_interval == 42


@pytest.mark.anyio
async def test_rss_heartbeat_upserts_after_success_and_preserves_last_success_on_failure(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    now = datetime(2026, 9, 21, tzinfo=UTC)
    monkeypatch.setattr("reven.background.utc_now", lambda: now)

    async def success() -> None:
        return None

    tick = RssDiscoveryTick(factory, success)
    await tick()
    await tick()
    async with factory() as session:
        heartbeat = await session.get(SystemState, "rss_discovery")
        assert heartbeat is not None
        assert heartbeat.value == {"last_heartbeat_at": now.isoformat()}
        assert heartbeat.updated_at == now
        assert await session.get(SystemState, "scheduler") is None

    async def failure() -> None:
        raise RuntimeError("failed RSS discovery")

    with pytest.raises(RuntimeError):
        await RssDiscoveryTick(factory, failure)()
    async with factory() as session:
        heartbeat = await session.get(SystemState, "rss_discovery")
        assert heartbeat is not None
        assert heartbeat.updated_at == now
