"""app lifespan 集成：启动时创建并 start FeishuBotSupervisor，关闭时 stop。"""

import asyncio
import base64

import pytest
from fastapi.testclient import TestClient
from reven.app import create_app
from reven.config import Settings
from reven.integrations.feishu_bot.chat_dispatcher import FeishuChatDispatcher
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

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
        assert client.get("/api/health").status_code == 503  # DB 不可达即 503（#177 健康检查语义）
        assert len(FakeSupervisor.instances) == 1
        supervisor = FakeSupervisor.instances[0]
        assert supervisor.started == 1
        assert client.app.state.feishu_bot_supervisor is supervisor
        assert isinstance(supervisor.chat_dispatcher, FeishuChatDispatcher)  # 对话分发器随 supervisor 装配
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

        async def send_markdown(self, *, chat_id: str | None, title: str, markdown: str, fallback_text: str) -> str:
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
