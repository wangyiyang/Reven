"""app lifespan 集成：启动时创建并 start FeishuBotSupervisor，关闭时 stop。"""

import base64

import pytest
from fastapi.testclient import TestClient
from reven.app import create_app
from reven.config import Settings
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

TEST_MASTER_KEY = base64.urlsafe_b64encode(b"t" * 32).decode()
DUMMY_DATABASE_URL = "postgresql+asyncpg://user:password@127.0.0.1:1/reven"


class FakeSupervisor:
    instances: list["FakeSupervisor"] = []

    def __init__(self, credentials: object) -> None:
        del credentials
        self.started = 0
        self.stopped = 0
        FakeSupervisor.instances.append(self)

    async def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1


def _factory() -> tuple[AsyncEngine, async_sessionmaker]:
    engine = create_async_engine(DUMMY_DATABASE_URL)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def test_lifespan_creates_starts_and_stops_feishu_bot_supervisor(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        database_url=DUMMY_DATABASE_URL,
        reven_master_key=TEST_MASTER_KEY,
        reven_admin_password="test-admin-password",
        agent_api_key=None,
        _env_file=None,
    )
    FakeSupervisor.instances = []
    monkeypatch.setattr("reven.app.FeishuBotSupervisor", FakeSupervisor)
    engine, factory = _factory()

    with TestClient(create_app(start_background_tasks=False, session_factory=factory, settings=settings)) as client:
        assert client.get("/api/health").status_code == 200
        assert len(FakeSupervisor.instances) == 1
        supervisor = FakeSupervisor.instances[0]
        assert supervisor.started == 1
        assert client.app.state.feishu_bot_supervisor is supervisor

    assert supervisor.stopped == 1


def test_lifespan_skips_supervisor_when_settings_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    # 模拟组合根解析失败：model_validate({}) 不读进程 env，缺必填字段必抛 ValidationError
    monkeypatch.setattr("reven.app.get_settings", lambda: Settings.model_validate({}))
    engine, factory = _factory()

    with TestClient(create_app(start_background_tasks=False, session_factory=factory)) as client:
        assert client.get("/api/health").status_code == 200
        assert getattr(client.app.state, "feishu_bot_supervisor", None) is None
