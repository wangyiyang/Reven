"""FeishuBotSupervisor 生命周期测试：配置驱动的起停与原子替换，全部使用假连接，不触真实 SDK。"""

import asyncio
import base64
import threading
import time
from collections.abc import Callable
from typing import Any

import pytest
from reven.config import Settings
from reven.integrations.credentials import IntegrationCredentials
from reven.integrations.feishu_bot.config import FeishuBotConfig
from reven.integrations.feishu_bot.supervisor import FeishuBotSupervisor
from reven.integrations.models import Integration
from reven.security.secrets import SecretBox
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

TEST_MASTER_KEY = base64.urlsafe_b64encode(b"m" * 32).decode()
BOT_SECRET = {"app_id": "cli_test", "app_secret": "s3cret-bot-value"}


def _factory(session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(session.bind, expire_on_commit=False)


def _secret_box() -> SecretBox:
    return SecretBox.from_base64(TEST_MASTER_KEY)


def _credentials(session: AsyncSession) -> IntegrationCredentials:
    settings = Settings(
        database_url="postgresql+asyncpg://unused:unused@127.0.0.1/unused",
        reven_master_key=TEST_MASTER_KEY,
        reven_admin_password="test-admin-password",
    )
    return IntegrationCredentials(_factory(session), settings)


class FakeBotApiClient:
    """FeishuBotApiClient 替身：避免 start/reload 触真实网络；类属性可模拟失败。"""

    error: Exception | None = None
    instances: list["FakeBotApiClient"] = []

    def __init__(self, app_id: str, app_secret: str) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.get_calls = 0
        FakeBotApiClient.instances.append(self)

    async def get_bot_open_id(self) -> str:
        self.get_calls += 1
        if FakeBotApiClient.error is not None:
            raise FakeBotApiClient.error
        return "ou_bot"


@pytest.fixture(autouse=True)
def _stub_bot_api_client(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeBotApiClient.error = None
    FakeBotApiClient.instances = []
    monkeypatch.setattr("reven.integrations.feishu_bot.supervisor.FeishuBotApiClient", FakeBotApiClient)


class FakeChatDispatcher:
    """ChatDispatch 替身：记录 bind_loop / submit 调用。"""

    def __init__(self) -> None:
        self.bound_loops: list[asyncio.AbstractEventLoop] = []
        self.submits: list[dict[str, Any]] = []

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self.bound_loops.append(loop)

    def submit(self, **kwargs: Any) -> None:
        self.submits.append(kwargs)


def _supervisor(
    session: AsyncSession,
    factory: "ConnectionFactoryStub | None" = None,
    dispatcher: FakeChatDispatcher | None = None,
) -> FeishuBotSupervisor:
    kwargs: dict[str, Any] = {"chat_dispatcher": dispatcher or FakeChatDispatcher()}
    if factory is not None:
        kwargs["connection_factory"] = factory
    return FeishuBotSupervisor(_credentials(session), **kwargs)


class FakeConnection:
    """假长连接：run 阻塞直到 shutdown，记录完整生命周期。"""

    def __init__(self, app_id: str, events: list[tuple[str, str]]) -> None:
        self.app_id = app_id
        self.run_started = threading.Event()
        self.shutdown_calls = 0
        self._events = events
        self._stop = threading.Event()

    def run(self) -> None:
        self.run_started.set()
        self._stop.wait(timeout=5)

    def shutdown(self) -> None:
        self.shutdown_calls += 1
        self._events.append(("stop", self.app_id))
        self._stop.set()


class ConnectionFactoryStub:
    def __init__(self) -> None:
        self.credentials: list[FeishuBotConfig] = []
        self.connections: list[FakeConnection] = []
        self.events: list[tuple[str, str]] = []

    def __call__(self, credentials: FeishuBotConfig) -> FakeConnection:
        self.credentials.append(credentials)
        connection = FakeConnection(credentials.app_id, self.events)
        self.connections.append(connection)
        self.events.append(("create", credentials.app_id))
        return connection


async def _wait_until(condition: Callable[[], bool], timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        await asyncio.sleep(0.02)
    return False


async def _write_bot_config(
    session: AsyncSession,
    *,
    enabled: bool,
    secret: dict[str, str] | None = BOT_SECRET,
) -> Integration:
    integration = Integration(
        provider="feishu_bot",
        public_config={"whitelist_open_ids": ["ou_boss"], "enabled": enabled},
        encrypted_secret=_secret_box().encrypt(secret) if secret is not None else None,
    )
    session.add(integration)
    await session.commit()
    return integration


@pytest.mark.anyio
async def test_start_without_config_spawns_no_connection(db_session: AsyncSession) -> None:
    factory = ConnectionFactoryStub()
    supervisor = _supervisor(db_session, factory)

    await supervisor.start()

    assert factory.credentials == []
    supervisor.stop()  # 无连接时停止是幂等空操作


@pytest.mark.anyio
async def test_start_with_disabled_config_spawns_no_connection(db_session: AsyncSession) -> None:
    await _write_bot_config(db_session, enabled=False)
    factory = ConnectionFactoryStub()
    supervisor = _supervisor(db_session, factory)

    await supervisor.start()

    assert factory.credentials == []


@pytest.mark.anyio
async def test_start_with_incomplete_secret_spawns_no_connection(db_session: AsyncSession) -> None:
    await _write_bot_config(db_session, enabled=True, secret={"app_id": "cli_test"})
    factory = ConnectionFactoryStub()
    supervisor = _supervisor(db_session, factory)

    await supervisor.start()

    assert factory.credentials == []


@pytest.mark.anyio
async def test_start_with_config_spawns_thread_and_passes_credentials(db_session: AsyncSession) -> None:
    await _write_bot_config(db_session, enabled=True)
    factory = ConnectionFactoryStub()
    supervisor = _supervisor(db_session, factory)

    await supervisor.start()

    assert factory.credentials == [
        FeishuBotConfig(app_id="cli_test", app_secret="s3cret-bot-value", whitelist_open_ids=("ou_boss",))
    ]
    connection = factory.connections[0]
    assert connection.run_started.wait(timeout=2)  # 连接线程确实在运行
    supervisor.stop()
    assert connection.shutdown_calls == 1


@pytest.mark.anyio
async def test_reload_replaces_connection_atomically(db_session: AsyncSession) -> None:
    integration = await _write_bot_config(db_session, enabled=True, secret={"app_id": "cli_old", "app_secret": "old"})
    factory = ConnectionFactoryStub()
    supervisor = _supervisor(db_session, factory)
    await supervisor.start()
    assert await _wait_until(lambda: len(factory.connections) == 1)

    integration.encrypted_secret = _secret_box().encrypt({"app_id": "cli_new", "app_secret": "new"})
    await db_session.commit()
    supervisor.reload()

    assert await _wait_until(lambda: len(factory.credentials) == 2)
    assert factory.credentials[1] == FeishuBotConfig(
        app_id="cli_new", app_secret="new", whitelist_open_ids=("ou_boss",)
    )
    # 原子替换顺序：先停旧连接，再按新配置建新连接
    assert factory.events == [("create", "cli_old"), ("stop", "cli_old"), ("create", "cli_new")]
    supervisor.stop()


@pytest.mark.anyio
async def test_reload_stops_connection_when_config_disabled(db_session: AsyncSession) -> None:
    integration = await _write_bot_config(db_session, enabled=True)
    factory = ConnectionFactoryStub()
    supervisor = _supervisor(db_session, factory)
    await supervisor.start()
    assert await _wait_until(lambda: len(factory.connections) == 1)

    integration.public_config = {"whitelist_open_ids": ["ou_boss"], "enabled": False}
    await db_session.commit()
    supervisor.reload()

    assert await _wait_until(lambda: factory.connections[0].shutdown_calls == 1)
    await asyncio.sleep(0.2)  # 宽限 reload 线程收尾，确认没有误建新连接
    assert len(factory.credentials) == 1


@pytest.mark.anyio
async def test_undecryptable_secret_is_logged_not_raised(db_session: AsyncSession) -> None:
    integration = Integration(
        provider="feishu_bot",
        public_config={"whitelist_open_ids": [], "enabled": True},
        encrypted_secret="v1:not-a-valid-ciphertext",
    )
    db_session.add(integration)
    await db_session.commit()
    factory = ConnectionFactoryStub()
    supervisor = _supervisor(db_session, factory)

    await supervisor.start()  # 解密失败只记日志，不阻断进程

    assert factory.credentials == []


@pytest.mark.anyio
async def test_config_read_exception_does_not_propagate(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenRepository:
        def __init__(self, session: AsyncSession) -> None:
            del session

        async def get_by_provider(self, provider: str) -> Integration | None:
            raise RuntimeError("database down")

    monkeypatch.setattr("reven.integrations.credentials.IntegrationRepository", BrokenRepository)
    factory = ConnectionFactoryStub()
    supervisor = _supervisor(db_session, factory)

    await supervisor.start()

    assert factory.credentials == []


@pytest.mark.anyio
async def test_start_and_stop_are_idempotent(db_session: AsyncSession) -> None:
    await _write_bot_config(db_session, enabled=True)
    factory = ConnectionFactoryStub()
    supervisor = _supervisor(db_session, factory)

    await supervisor.start()
    await supervisor.start()  # 已在运行：不重复建连接
    assert len(factory.credentials) == 1

    supervisor.stop()
    supervisor.stop()  # 已停止：幂等
    assert factory.connections[0].shutdown_calls == 1

    await supervisor.start()  # 停止后可再次启动
    assert len(factory.credentials) == 2
    supervisor.stop()


@pytest.mark.anyio
async def test_default_connection_factory_registers_only_im_processor(db_session: AsyncSession) -> None:
    supervisor = _supervisor(db_session)

    connection = supervisor._build_default_connection(
        FeishuBotConfig(app_id="cli_test", app_secret="s", whitelist_open_ids=())
    )

    event_handler = connection._client._event_handler
    assert "p2.im.message.receive_v1" in event_handler._processorMap
    assert "p2.card.action.trigger" not in event_handler._callback_processor_map


@pytest.mark.anyio
async def test_start_binds_main_loop_and_fetches_bot_open_id(db_session: AsyncSession) -> None:
    await _write_bot_config(db_session, enabled=True)
    factory = ConnectionFactoryStub()
    dispatcher = FakeChatDispatcher()
    supervisor = _supervisor(db_session, factory, dispatcher)

    await supervisor.start()

    assert dispatcher.bound_loops == [asyncio.get_running_loop()]
    assert supervisor._bot_open_id == "ou_bot"
    assert [client.app_id for client in FakeBotApiClient.instances] == ["cli_test"]
    supervisor.stop()


@pytest.mark.anyio
async def test_default_connection_receives_bot_open_id_and_dispatcher(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    class FakeLarkConnection:
        def __init__(self, credentials: FeishuBotConfig, *, bot_open_id: str | None, chat_dispatch: object) -> None:
            captured["credentials"] = credentials
            captured["bot_open_id"] = bot_open_id
            captured["chat_dispatch"] = chat_dispatch

    monkeypatch.setattr("reven.integrations.feishu_bot.supervisor.LarkWsConnection", FakeLarkConnection)
    dispatcher = FakeChatDispatcher()
    supervisor = _supervisor(db_session, dispatcher=dispatcher)
    supervisor._bot_open_id = "ou_bot"
    config = FeishuBotConfig(app_id="cli_test", app_secret="s", whitelist_open_ids=())

    supervisor._build_default_connection(config)

    assert captured == {"credentials": config, "bot_open_id": "ou_bot", "chat_dispatch": dispatcher}


@pytest.mark.anyio
async def test_bot_open_id_failure_degrades_group_chat_but_keeps_connection(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    await _write_bot_config(db_session, enabled=True)
    factory = ConnectionFactoryStub()
    supervisor = _supervisor(db_session, factory)
    FakeBotApiClient.error = RuntimeError("network down")

    with caplog.at_level("WARNING"):
        await supervisor.start()

    assert supervisor._bot_open_id is None  # 降级：群聊忽略，私聊对话不受影响
    assert len(factory.connections) == 1
    assert "open_id 获取失败" in caplog.text
    assert "network down" not in caplog.text  # 日志脱敏：只记异常类型
    supervisor.stop()


@pytest.mark.anyio
async def test_reload_retries_bot_open_id_fetch_after_failure(db_session: AsyncSession) -> None:
    await _write_bot_config(db_session, enabled=True)
    factory = ConnectionFactoryStub()
    supervisor = _supervisor(db_session, factory)
    FakeBotApiClient.error = RuntimeError("network down")
    await supervisor.start()
    assert await _wait_until(lambda: len(factory.connections) == 1)
    assert supervisor._bot_open_id is None

    FakeBotApiClient.error = None
    supervisor.reload()

    assert await _wait_until(lambda: supervisor._bot_open_id == "ou_bot")
    assert len(FakeBotApiClient.instances) == 2  # 首次失败后 reload 重试成功
    supervisor.stop()


@pytest.mark.anyio
async def test_reload_before_start_is_ignored(db_session: AsyncSession, caplog: pytest.LogCaptureFixture) -> None:
    supervisor = _supervisor(db_session)

    with caplog.at_level("WARNING"):
        supervisor.reload()  # 主事件循环尚未就绪：仅记日志，不建连接
        await asyncio.sleep(0.2)

    assert "主事件循环尚未就绪" in caplog.text


@pytest.mark.anyio
async def test_reload_with_dead_loop_closes_coroutine_and_stops(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    await _write_bot_config(db_session, enabled=True)
    factory = ConnectionFactoryStub()
    supervisor = _supervisor(db_session, factory)
    dead_loop = asyncio.new_event_loop()
    dead_loop.close()
    supervisor._main_loop = dead_loop

    with caplog.at_level("WARNING"):
        supervisor.reload()  # 调度失败：协程已 close，不建连接
        await asyncio.sleep(0.2)

    assert factory.credentials == []
    assert "配置热更新读取失败" in caplog.text


def test_credentials_repr_hides_secrets() -> None:
    credentials = FeishuBotConfig(app_id="cli_test", app_secret="s3cret-bot-value", whitelist_open_ids=())

    text = repr(credentials)
    assert "s3cret-bot-value" not in text
    assert "cli_test" not in text
