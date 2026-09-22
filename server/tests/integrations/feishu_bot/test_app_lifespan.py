"""app lifespan 集成：启动时创建并 start FeishuBotSupervisor，关闭时 stop。"""

import base64

import pytest
from fastapi.testclient import TestClient
from reven.app import create_app
from reven.config import get_settings
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

TEST_MASTER_KEY = base64.urlsafe_b64encode(b"t" * 32).decode()
DUMMY_DATABASE_URL = "postgresql+asyncpg://user:password@127.0.0.1:1/reven"


class FakeSupervisor:
    instances: list["FakeSupervisor"] = []

    def __init__(self, credentials: object, review_callback: object = None) -> None:
        del credentials, review_callback
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
    monkeypatch.setenv("DATABASE_URL", DUMMY_DATABASE_URL)
    monkeypatch.setenv("REVEN_MASTER_KEY", TEST_MASTER_KEY)
    monkeypatch.setenv("REVEN_ADMIN_PASSWORD", "test-admin-password")
    get_settings.cache_clear()
    FakeSupervisor.instances = []
    monkeypatch.setattr("reven.app.FeishuBotSupervisor", FakeSupervisor)
    engine, factory = _factory()

    with TestClient(create_app(start_background_tasks=False, session_factory=factory)) as client:
        assert client.get("/api/health").status_code == 200
        assert len(FakeSupervisor.instances) == 1
        supervisor = FakeSupervisor.instances[0]
        assert supervisor.started == 1
        assert client.app.state.feishu_bot_supervisor is supervisor

    assert supervisor.stopped == 1
    get_settings.cache_clear()


def test_lifespan_skips_supervisor_when_settings_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in ("DATABASE_URL", "REVEN_MASTER_KEY", "REVEN_ADMIN_PASSWORD"):
        monkeypatch.delenv(variable, raising=False)
    get_settings.cache_clear()
    engine, factory = _factory()

    with TestClient(create_app(start_background_tasks=False, session_factory=factory)) as client:
        assert client.get("/api/health").status_code == 200
        assert getattr(client.app.state, "feishu_bot_supervisor", None) is None

    get_settings.cache_clear()
