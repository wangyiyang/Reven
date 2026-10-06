import asyncio
import base64
import os

import pytest
from fastapi.testclient import TestClient
from reven.agent.checkpoint import AgentCheckpoints, postgres_conninfo
from reven.app import create_app
from reven.background import BackgroundRunner
from reven.config import Settings
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

DUMMY_DATABASE_URL = "postgresql+asyncpg://user:password@127.0.0.1:1/reven"
TEST_MASTER_KEY = base64.urlsafe_b64encode(b"t" * 32).decode()


def _settings(database_url: str = DUMMY_DATABASE_URL, **overrides: object) -> Settings:
    """显式构造测试 Settings：不读进程 env（含 .env），lifespan 不再依赖外部环境。"""
    values: dict[str, object] = {
        "database_url": database_url,
        "reven_master_key": TEST_MASTER_KEY,
        "reven_admin_password": "test-admin-password",
        "agent_api_key": None,
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def reject_dummy_checkpointer_without_pool_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    original = AgentCheckpoints.open

    async def open_pool(pool: AgentCheckpoints) -> None:
        if pool._conninfo == postgres_conninfo(DUMMY_DATABASE_URL):
            raise OSError("dummy checkpoint unavailable")
        await original(pool)

    monkeypatch.setattr(AgentCheckpoints, "open", open_pool)


class FakeRunner:
    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0

    async def start(self) -> None:
        self.started += 1

    async def stop(self) -> None:
        self.stopped += 1


def test_health_db_unreachable_returns_503() -> None:
    """db 失败即 503（#177）：驱动 LB/哨兵摘流，杜绝静态 200 误判部署成功。"""
    with TestClient(create_app(start_background_tasks=False, settings=_settings())) as client:
        response = client.get("/api/health")

    assert response.status_code == 503
    assert response.json() == {
        "service": "reven",
        "status": "fail",
        "checks": {
            "db": {"status": "fail"},
            "agent": {"status": "disabled"},  # 未配置 agent_api_key
            "checkpointer": {"status": "degraded"},
            "background_runner": {"status": "disabled"},  # start_background_tasks=False
        },
    }


def _real_database_url() -> str:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("TEST_DATABASE_URL is not set, skipping integration tests")
    return database_url


def test_health_all_ok_returns_structured_details() -> None:
    """全链路健康：200 + status ok + 原生检查明细（agent/runner 未启用为 disabled，不拖累整体）。"""
    database_url = _real_database_url()
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    settings = _settings(database_url)
    with TestClient(create_app(start_background_tasks=False, session_factory=factory, settings=settings)) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "service": "reven",
        "status": "ok",
        "checks": {
            "db": {"status": "ok"},
            "agent": {"status": "disabled"},
            "checkpointer": {"status": "ok"},
            "background_runner": {"status": "disabled"},
        },
    }
    asyncio.run(engine.dispose())


def test_health_checkpointer_start_failed_shows_degraded_but_stays_200(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """检查点启动失败：字段显式 degraded、保持 200（不触发重启风暴），供监控抓（#177 验收）。"""
    database_url = _real_database_url()

    async def _fail_open(pool: AgentCheckpoints) -> None:
        del pool
        raise OSError("checkpoint unavailable")

    monkeypatch.setattr(AgentCheckpoints, "open", _fail_open)
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    settings = _settings(database_url, agent_api_key="test-agent-key")
    with TestClient(create_app(start_background_tasks=False, session_factory=factory, settings=settings)) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["db"] == {"status": "ok"}
    assert body["checks"]["agent"] == {"status": "degraded"}
    assert body["checks"]["checkpointer"] == {"status": "degraded"}
    asyncio.run(engine.dispose())


def test_health_dead_background_runner_shows_degraded() -> None:
    """后台 runner 主循环任务死亡：degraded + 200；存活则 ok（#177）。"""
    database_url = _real_database_url()
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    settings = _settings(database_url)

    async def tick() -> None:
        await asyncio.Future()

    with TestClient(create_app(start_background_tasks=False, session_factory=factory, settings=settings)) as client:
        runner = BackgroundRunner(tick)

        async def start_and_kill() -> None:
            await runner.start()
            assert runner.healthy
            for task in runner.tasks:
                task.cancel()

        asyncio.run(start_and_kill())
        assert not runner.healthy
        client.app.state.background_runner = runner
        response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["background_runner"] == {"status": "degraded"}
    asyncio.run(engine.dispose())


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
