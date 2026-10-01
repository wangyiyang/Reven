"""app lifespan 集成：启动时创建并 start FeishuBotSupervisor，关闭时 stop。"""

import base64
from typing import cast

import pytest
from agent_service_support import DEFAULT_REF, EXTRA_REF, ServiceRig
from fastapi import Request
from fastapi.testclient import TestClient
from reven.agent.service import AgentService
from reven.api.dependencies import get_agent_service
from reven.app import create_app
from reven.config import Settings
from reven.integrations.credentials import IntegrationCredentials
from reven.integrations.feishu_bot.chat_dispatcher import FeishuChatDispatcher
from reven.provider_clients import FeishuReplier, ProviderClients
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

TEST_MASTER_KEY = base64.urlsafe_b64encode(b"t" * 32).decode()
DUMMY_DATABASE_URL = "postgresql+asyncpg://user:password@127.0.0.1:1/reven"


class FakeSupervisor:
    instances: list["FakeSupervisor"] = []

    def __init__(self, credentials: object, *, chat_dispatcher: object) -> None:
        del credentials
        self.chat_dispatcher = chat_dispatcher
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
    reply_clients: list[ProviderClients] = []

    def build_replier(clients: ProviderClients) -> FeishuReplier:
        reply_clients.append(clients)
        return FeishuReplier(clients)

    settings = Settings(
        database_url=DUMMY_DATABASE_URL,
        reven_master_key=TEST_MASTER_KEY,
        reven_admin_password="test-admin-password",
        agent_api_key=None,
        _env_file=None,
    )
    FakeSupervisor.instances = []
    monkeypatch.setattr("reven.app.FeishuBotSupervisor", FakeSupervisor)
    monkeypatch.setattr("reven.app.FeishuReplier", build_replier)
    engine, factory = _factory()

    with TestClient(create_app(start_background_tasks=False, session_factory=factory, settings=settings)) as client:
        assert client.get("/api/health").status_code == 200
        assert len(FakeSupervisor.instances) == 1
        supervisor = FakeSupervisor.instances[0]
        assert supervisor.started == 1
        assert client.app.state.feishu_bot_supervisor is supervisor
        assert isinstance(supervisor.chat_dispatcher, FeishuChatDispatcher)  # 对话分发器随 supervisor 装配
        assert reply_clients == [client.app.state.provider_clients]
        service = client.app.state.agent_service
        assert isinstance(service, AgentService)
        assert supervisor.chat_dispatcher._agent is service
        request = Request({"type": "http", "app": client.app})
        assert get_agent_service(request) is get_agent_service(request) is service

    assert supervisor.stopped == 1


def test_lifespan_skips_supervisor_when_settings_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    # 模拟组合根解析失败：model_validate({}) 不读进程 env，缺必填字段必抛 ValidationError
    monkeypatch.setattr("reven.app.get_settings", lambda: Settings.model_validate({}))
    engine, factory = _factory()

    with TestClient(create_app(start_background_tasks=False, session_factory=factory)) as client:
        assert client.get("/api/health").status_code == 200
        assert getattr(client.app.state, "feishu_bot_supervisor", None) is None
        assert isinstance(client.app.state.agent_service, AgentService)


def test_each_app_lifespan_has_independent_model_choices(tmp_path, monkeypatch) -> None:
    rig = ServiceRig(tmp_path, monkeypatch)
    monkeypatch.setattr("reven.app.FeishuBotSupervisor", FakeSupervisor)

    def clients_for_app(factory, settings):
        return ProviderClients(cast(IntegrationCredentials, rig.credentials), settings)

    async def runtime_for_app(credentials, settings, mcp):
        _, runtime = await rig.build()
        return runtime

    monkeypatch.setattr("reven.app._build_provider_clients", clients_for_app)
    monkeypatch.setattr("reven.app._build_agent_runtime", runtime_for_app)
    _, factory = _factory()
    first_app = create_app(start_background_tasks=False, session_factory=factory, settings=rig.settings)
    second_app = create_app(start_background_tasks=False, session_factory=factory, settings=rig.settings)
    with TestClient(first_app) as first, TestClient(second_app) as second:
        first_service, second_service = first.app.state.agent_service, second.app.state.agent_service
        assert first_service is not second_service
        first.portal.call(first_service.use_model, "sid", EXTRA_REF)
        assert first.portal.call(first_service.model_state, "sid").current_ref == EXTRA_REF
        second_state = second.portal.call(second_service.model_state, "sid")
        assert second_state.current_ref == DEFAULT_REF and not second_state.is_override
        assert first.app.state.feishu_bot_supervisor.chat_dispatcher._agent is first_service
        assert second.app.state.feishu_bot_supervisor.chat_dispatcher._agent is second_service
    assert all(instance.closed for instance in rig.instances)


def test_agent_dependency_requires_initialized_service() -> None:
    app = create_app(start_background_tasks=False)
    request = Request({"type": "http", "app": app})
    with pytest.raises(RuntimeError, match="Agent 服务未初始化"):
        get_agent_service(request)


def test_lifespan_cleanup_logs_redact_exception_messages(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """#176 P1 回归：lifespan 清理路径只记 error_type——组件异常原文（可能含凭证）不进日志。"""

    class SecretBearingSupervisor:
        def __init__(self, credentials: object, *, chat_dispatcher: object) -> None:
            del credentials, chat_dispatcher

        async def start(self) -> None:
            pass

        def stop(self) -> None:
            raise RuntimeError("cleanup failed, credential=sk-live-secret")

    settings = Settings(
        database_url=DUMMY_DATABASE_URL,
        reven_master_key=TEST_MASTER_KEY,
        reven_admin_password="test-admin-password",
        agent_api_key=None,
        _env_file=None,
    )
    monkeypatch.setattr("reven.app.FeishuBotSupervisor", SecretBearingSupervisor)
    engine, factory = _factory()

    with caplog.at_level("ERROR", logger="reven.app"), pytest.raises(RuntimeError, match="sk-live-secret"):
        with TestClient(create_app(start_background_tasks=False, session_factory=factory, settings=settings)):
            pass

    assert "sk-live-secret" not in caplog.text
    assert "error_type=RuntimeError" in caplog.text
