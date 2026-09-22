import asyncio
import base64

import pytest
from fastapi.testclient import TestClient
from reven.app import create_app
from reven.config import Settings
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

DUMMY_DATABASE_URL = "postgresql+asyncpg://user:password@127.0.0.1:1/reven"
TEST_MASTER_KEY = base64.urlsafe_b64encode(b"t" * 32).decode()


def _settings() -> Settings:
    """显式构造测试 Settings：不读进程 env（含 .env），lifespan 不再依赖外部环境。"""
    return Settings(
        database_url=DUMMY_DATABASE_URL,
        reven_master_key=TEST_MASTER_KEY,
        reven_admin_password="test-admin-password",
        agent_api_key=None,
        _env_file=None,
    )


class FakeRunner:
    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0

    async def start(self) -> None:
        self.started += 1

    async def stop(self) -> None:
        self.stopped += 1


def test_health_returns_service_status() -> None:
    with TestClient(create_app(start_background_tasks=False, settings=_settings())) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"service": "reven", "status": "ok"}


def test_lifespan_starts_and_stops_injected_runner() -> None:
    runner = FakeRunner()

    with TestClient(create_app(runner=runner, settings=_settings())):
        assert runner.started == 1

    assert runner.stopped == 1


def test_default_background_runner_is_built_started_and_stopped(
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    runner = FakeRunner()
    engine = create_async_engine(DUMMY_DATABASE_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    built_with = None

    def fake_build(candidate, clients, settings):  # type: ignore[no-untyped-def]
        nonlocal built_with
        built_with = candidate
        return runner

    monkeypatch.setattr("reven.app.build_background_runner", fake_build)
    with TestClient(create_app(session_factory=factory, settings=_settings())):
        assert runner.started == 1

    assert runner.stopped == 1
    assert built_with is factory
    asyncio.run(engine.dispose())


def test_runner_start_failure_does_not_dispose_injected_engine(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class StartFailure(FakeRunner):
        async def start(self) -> None:
            raise RuntimeError("start failed")

    disposed = False
    engine = create_async_engine(DUMMY_DATABASE_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    original_dispose = AsyncEngine.dispose

    async def track_dispose(target: AsyncEngine) -> None:
        nonlocal disposed
        if target is engine:
            disposed = True
        await original_dispose(target)

    monkeypatch.setattr(AsyncEngine, "dispose", track_dispose)
    with pytest.raises(RuntimeError, match="start failed"):
        with TestClient(create_app(session_factory=factory, runner=StartFailure(), settings=_settings())):
            pass
    assert disposed is False
    asyncio.run(engine.dispose())


def test_runner_stop_failure_propagates_after_disposing_internal_engine(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class StopFailure(FakeRunner):
        async def stop(self) -> None:
            raise RuntimeError("stop failed")

    engine = create_async_engine(DUMMY_DATABASE_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    disposed = False
    original_dispose = AsyncEngine.dispose

    async def track_dispose(target: AsyncEngine) -> None:
        nonlocal disposed
        if target is engine:
            disposed = True
        await original_dispose(target)

    monkeypatch.setattr("reven.app.create_session_factory", lambda settings: factory)
    monkeypatch.setattr(AsyncEngine, "dispose", track_dispose)

    with pytest.raises(RuntimeError, match="stop failed"):
        with TestClient(create_app(runner=StopFailure(), settings=_settings())):
            pass

    assert disposed is True


def test_runner_build_failure_disposes_internal_engine(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    engine = create_async_engine(DUMMY_DATABASE_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    disposed = False
    original_dispose = AsyncEngine.dispose

    async def track_dispose(target: AsyncEngine) -> None:
        nonlocal disposed
        if target is engine:
            disposed = True
        await original_dispose(target)

    monkeypatch.setattr("reven.app.create_session_factory", lambda settings: factory)
    monkeypatch.setattr(
        "reven.app.build_background_runner",
        lambda candidate, clients, settings: (_ for _ in ()).throw(RuntimeError("build failed")),
    )
    monkeypatch.setattr(AsyncEngine, "dispose", track_dispose)

    with pytest.raises(RuntimeError, match="build failed"):
        with TestClient(create_app(settings=_settings())):
            pass

    assert disposed is True


def test_runner_build_failure_does_not_dispose_external_engine(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    engine = create_async_engine(DUMMY_DATABASE_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(
        "reven.app.build_background_runner",
        lambda candidate, clients, settings: (_ for _ in ()).throw(RuntimeError("build failed")),
    )

    with pytest.raises(RuntimeError, match="build failed"):
        with TestClient(create_app(session_factory=factory, settings=_settings())):
            pass

    asyncio.run(engine.dispose())


def test_start_error_has_priority_over_stop_error() -> None:
    class BothFail(FakeRunner):
        async def start(self) -> None:
            raise ValueError("start")

        async def stop(self) -> None:
            raise RuntimeError("stop")

    with pytest.raises(ValueError, match="start"):
        with TestClient(create_app(runner=BothFail(), settings=_settings())):
            pass


@pytest.mark.anyio
async def test_body_error_has_priority_over_stop_error() -> None:
    class StopFailure(FakeRunner):
        async def stop(self) -> None:
            raise RuntimeError("stop")

    with pytest.raises(ValueError, match="body"):
        app = create_app(runner=StopFailure(), settings=_settings())
        async with app.router.lifespan_context(app):
            raise ValueError("body")


def test_stop_error_has_priority_over_dispose_error(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class StopFailure(FakeRunner):
        async def stop(self) -> None:
            raise RuntimeError("stop")

    engine = create_async_engine(DUMMY_DATABASE_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def dispose_failure(target: AsyncEngine) -> None:
        if target is engine:
            raise OSError("dispose")

    monkeypatch.setattr("reven.app.create_session_factory", lambda settings: factory)
    monkeypatch.setattr(AsyncEngine, "dispose", dispose_failure)

    with pytest.raises(RuntimeError, match="stop"):
        with TestClient(create_app(runner=StopFailure(), settings=_settings())):
            pass
