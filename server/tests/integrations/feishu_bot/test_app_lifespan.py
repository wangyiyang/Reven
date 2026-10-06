"""app lifespan 集成：启动时创建并 start FeishuBotSupervisor，关闭时 stop。"""

import asyncio
import base64
import os
from typing import cast

import pytest
from agent_service_support import EXTRA_REF, ServiceRig
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
from sqlalchemy.pool import NullPool

TEST_MASTER_KEY = base64.urlsafe_b64encode(b"t" * 32).decode()
DUMMY_DATABASE_URL = "postgresql+asyncpg://user:password@127.0.0.1:1/reven"


class FakeSupervisor:
    instances: list["FakeSupervisor"] = []
    on_unexpected_exit: object = None  # 组合根装配的死亡告警钩子（#177）

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
        assert client.get("/api/health").status_code == 503  # DB 不可达即 503（#177 健康检查语义）
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
        assert callable(supervisor.on_unexpected_exit)  # 死亡告警钩子随 clients 装配（#177）

    assert supervisor.stopped == 1


@pytest.mark.anyio
async def test_exit_alerter_schedules_notification_on_main_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """死亡告警钩子（#177）：把投递协程调度回主事件循环，经 notify 通道送达（白名单兜底）。"""
    from types import SimpleNamespace

    from reven.app import _build_feishu_exit_alerter

    sent: list[dict[str, object]] = []

    class FakeNotifier:
        def __init__(self, clients: object) -> None:
            del clients

        async def send_markdown(self, *, chat_id: str | None, title: str, markdown: str) -> str:
            sent.append({"chat_id": chat_id, "title": title, "markdown": markdown})
            return "whitelist"

    monkeypatch.setattr("reven.app.FeishuProactiveNotifier", FakeNotifier)
    supervisor = SimpleNamespace(main_loop=asyncio.get_running_loop())
    alerter = _build_feishu_exit_alerter(object(), supervisor)  # type: ignore[arg-type]

    alerter("飞书机器人长连接意外终止")
    await asyncio.sleep(0.1)

    assert sent == [{"chat_id": None, "title": "Reven 告警", "markdown": "飞书机器人长连接意外终止"}]


def test_exit_alerter_without_main_loop_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    """主事件循环未就绪/已关闭时告警静默跳过（进程收尾期不抛异常）。"""
    from types import SimpleNamespace

    from reven.app import _build_feishu_exit_alerter

    alerter = _build_feishu_exit_alerter(object(), SimpleNamespace(main_loop=None))  # type: ignore[arg-type]
    alerter("任意消息")  # 不抛异常即通过


def test_lifespan_skips_supervisor_when_settings_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    # 模拟组合根解析失败：model_validate({}) 不读进程 env，缺必填字段必抛 ValidationError
    monkeypatch.setattr("reven.app.get_settings", lambda: Settings.model_validate({}))
    engine, factory = _factory()

    with TestClient(create_app(start_background_tasks=False, session_factory=factory)) as client:
        assert client.get("/api/health").status_code == 503  # DB 不可达即 503（#177 健康检查语义）
        assert getattr(client.app.state, "feishu_bot_supervisor", None) is None
        assert isinstance(client.app.state.agent_service, AgentService)


@pytest.mark.anyio
async def test_app_recreation_restores_database_model_choice(db_session, monkeypatch) -> None:
    database_url = os.environ["TEST_DATABASE_URL"]
    engines = [create_async_engine(database_url, poolclass=NullPool) for _ in range(2)]
    factories = [async_sessionmaker(engine, expire_on_commit=False) for engine in engines]
    rigs = [ServiceRig(factory) for factory in factories]
    settings = Settings(
        database_url=database_url,
        reven_master_key=TEST_MASTER_KEY,
        reven_admin_password="test-admin-password",
        _env_file=None,
    )
    monkeypatch.setattr("reven.app.FeishuBotSupervisor", FakeSupervisor)

    def clients_for_app(factory, settings):
        rig = rigs[factories.index(factory)]
        return ProviderClients(cast(IntegrationCredentials, rig.credentials), settings)

    async def runtime_for_app(credentials, settings, factory, embedding_refresher):
        rig = rigs[factories.index(factory)]
        service, runtime = await rig.build()
        await service.close()
        return runtime

    monkeypatch.setattr("reven.app._build_provider_clients", clients_for_app)
    monkeypatch.setattr("reven.app._build_agent_runtime", runtime_for_app)
    first_app = create_app(start_background_tasks=False, session_factory=factories[0], settings=settings)
    second_app = create_app(start_background_tasks=False, session_factory=factories[1], settings=settings)
    with TestClient(first_app) as first:
        first_service = first.app.state.agent_service
        first.portal.call(first_service.use_model, "sid", EXTRA_REF)
        assert first.portal.call(first_service.model_state, "sid").current_ref == EXTRA_REF
        assert first.app.state.feishu_bot_supervisor.chat_dispatcher._agent is first_service
    with TestClient(second_app) as second:
        second_service = second.app.state.agent_service
        assert first_service is not second_service
        second_state = second.portal.call(second_service.model_state, "sid")
        assert second_state.current_ref == EXTRA_REF and second_state.is_override
        assert second.app.state.feishu_bot_supervisor.chat_dispatcher._agent is second_service
    for engine in engines:
        await engine.dispose()


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
