import asyncio
import os

import pytest
from fastapi.testclient import TestClient
from reven.app import create_app
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine


class FakeRunner:
    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0

    async def start(self) -> None:
        self.started += 1

    async def stop(self) -> None:
        self.stopped += 1


def test_health_returns_service_status() -> None:
    with TestClient(create_app(start_background_tasks=False)) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"service": "reven", "status": "ok"}


def test_lifespan_starts_and_stops_injected_runner() -> None:
    runner = FakeRunner()

    with TestClient(create_app(runner=runner)):
        assert runner.started == 1

    assert runner.stopped == 1


def test_default_background_runner_is_built_started_and_stopped(
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    runner = FakeRunner()
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    built_with = None

    def fake_build(candidate):  # type: ignore[no-untyped-def]
        nonlocal built_with
        built_with = candidate
        return runner

    monkeypatch.setattr("reven.app.build_background_runner", fake_build)
    with TestClient(create_app(session_factory=factory)):
        assert runner.started == 1

    assert runner.stopped == 1
    assert built_with is factory
    asyncio.run(engine.dispose())


def test_runner_start_failure_does_not_dispose_injected_engine(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class StartFailure(FakeRunner):
        async def start(self) -> None:
            raise RuntimeError("start failed")

    disposed = False
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)

    original_dispose = AsyncEngine.dispose

    async def track_dispose(target: AsyncEngine) -> None:
        nonlocal disposed
        if target is engine:
            disposed = True
        await original_dispose(target)

    monkeypatch.setattr(AsyncEngine, "dispose", track_dispose)
    with pytest.raises(RuntimeError, match="start failed"):
        with TestClient(create_app(session_factory=factory, runner=StartFailure())):
            pass
    assert disposed is False
    asyncio.run(engine.dispose())


def test_runner_stop_failure_propagates_after_disposing_internal_engine(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class StopFailure(FakeRunner):
        async def stop(self) -> None:
            raise RuntimeError("stop failed")

    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    disposed = False
    original_dispose = AsyncEngine.dispose

    async def track_dispose(target: AsyncEngine) -> None:
        nonlocal disposed
        if target is engine:
            disposed = True
        await original_dispose(target)

    monkeypatch.setattr("reven.app.get_settings", lambda: object())
    monkeypatch.setattr("reven.app.create_session_factory", lambda settings: factory)
    monkeypatch.setattr(AsyncEngine, "dispose", track_dispose)

    with pytest.raises(RuntimeError, match="stop failed"):
        with TestClient(create_app(runner=StopFailure())):
            pass

    assert disposed is True
