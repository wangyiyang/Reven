"""FeishuBotSupervisor 生命周期测试：配置驱动的起停与原子替换，全部使用假连接，不触真实 SDK。"""

import asyncio
import base64
import threading
import time
from collections.abc import Callable
from uuid import UUID

import pytest
from reven.integrations.feishu_bot.review_callback import ReviewActionOutcome
from reven.integrations.feishu_bot.supervisor import FeishuBotCredentials, FeishuBotSupervisor, LarkWsConnection
from reven.integrations.models import Integration
from reven.security.secrets import SecretBox
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

TEST_MASTER_KEY = base64.urlsafe_b64encode(b"m" * 32).decode()
BOT_SECRET = {"app_id": "cli_test", "app_secret": "s3cret-bot-value"}


def _factory(session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(session.bind, expire_on_commit=False)


def _secret_box() -> SecretBox:
    return SecretBox.from_base64(TEST_MASTER_KEY)


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
        self.credentials: list[FeishuBotCredentials] = []
        self.connections: list[FakeConnection] = []
        self.events: list[tuple[str, str]] = []

    def __call__(self, credentials: FeishuBotCredentials) -> FakeConnection:
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
    supervisor = FeishuBotSupervisor(_factory(db_session), _secret_box(), connection_factory=factory)

    await supervisor.start()

    assert factory.credentials == []
    supervisor.stop()  # 无连接时停止是幂等空操作


@pytest.mark.anyio
async def test_start_with_disabled_config_spawns_no_connection(db_session: AsyncSession) -> None:
    await _write_bot_config(db_session, enabled=False)
    factory = ConnectionFactoryStub()
    supervisor = FeishuBotSupervisor(_factory(db_session), _secret_box(), connection_factory=factory)

    await supervisor.start()

    assert factory.credentials == []


@pytest.mark.anyio
async def test_start_with_incomplete_secret_spawns_no_connection(db_session: AsyncSession) -> None:
    await _write_bot_config(db_session, enabled=True, secret={"app_id": "cli_test"})
    factory = ConnectionFactoryStub()
    supervisor = FeishuBotSupervisor(_factory(db_session), _secret_box(), connection_factory=factory)

    await supervisor.start()

    assert factory.credentials == []


@pytest.mark.anyio
async def test_start_with_config_spawns_thread_and_passes_credentials(db_session: AsyncSession) -> None:
    await _write_bot_config(db_session, enabled=True)
    factory = ConnectionFactoryStub()
    supervisor = FeishuBotSupervisor(_factory(db_session), _secret_box(), connection_factory=factory)

    await supervisor.start()

    assert factory.credentials == [FeishuBotCredentials(app_id="cli_test", app_secret="s3cret-bot-value")]
    connection = factory.connections[0]
    assert connection.run_started.wait(timeout=2)  # 连接线程确实在运行
    supervisor.stop()
    assert connection.shutdown_calls == 1


@pytest.mark.anyio
async def test_reload_replaces_connection_atomically(db_session: AsyncSession) -> None:
    integration = await _write_bot_config(db_session, enabled=True, secret={"app_id": "cli_old", "app_secret": "old"})
    factory = ConnectionFactoryStub()
    supervisor = FeishuBotSupervisor(_factory(db_session), _secret_box(), connection_factory=factory)
    await supervisor.start()
    assert await _wait_until(lambda: len(factory.connections) == 1)

    integration.encrypted_secret = _secret_box().encrypt({"app_id": "cli_new", "app_secret": "new"})
    await db_session.commit()
    supervisor.reload()

    assert await _wait_until(lambda: len(factory.credentials) == 2)
    assert factory.credentials[1] == FeishuBotCredentials(app_id="cli_new", app_secret="new")
    # 原子替换顺序：先停旧连接，再按新配置建新连接
    assert factory.events == [("create", "cli_old"), ("stop", "cli_old"), ("create", "cli_new")]
    supervisor.stop()


@pytest.mark.anyio
async def test_reload_stops_connection_when_config_disabled(db_session: AsyncSession) -> None:
    integration = await _write_bot_config(db_session, enabled=True)
    factory = ConnectionFactoryStub()
    supervisor = FeishuBotSupervisor(_factory(db_session), _secret_box(), connection_factory=factory)
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
    supervisor = FeishuBotSupervisor(_factory(db_session), _secret_box(), connection_factory=factory)

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

    monkeypatch.setattr("reven.integrations.feishu_bot.config.IntegrationRepository", BrokenRepository)
    factory = ConnectionFactoryStub()
    supervisor = FeishuBotSupervisor(_factory(db_session), _secret_box(), connection_factory=factory)

    await supervisor.start()

    assert factory.credentials == []


@pytest.mark.anyio
async def test_start_and_stop_are_idempotent(db_session: AsyncSession) -> None:
    await _write_bot_config(db_session, enabled=True)
    factory = ConnectionFactoryStub()
    supervisor = FeishuBotSupervisor(_factory(db_session), _secret_box(), connection_factory=factory)

    await supervisor.start()
    await supervisor.start()  # 已在运行：不重复建连接
    assert len(factory.credentials) == 1

    supervisor.stop()
    supervisor.stop()  # 已停止：幂等
    assert factory.connections[0].shutdown_calls == 1

    await supervisor.start()  # 停止后可再次启动
    assert len(factory.credentials) == 2
    supervisor.stop()


class ReviewCallbackStub:
    """假审核回调：只记录主循环绑定，生命周期测试中不应被调用。"""

    def __init__(self) -> None:
        self.bound_loops: list[asyncio.AbstractEventLoop] = []

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self.bound_loops.append(loop)

    def __call__(self, action: str, item_id: UUID, operator_open_id: str | None) -> ReviewActionOutcome:
        raise AssertionError("生命周期测试不触发审核回调")


@pytest.mark.anyio
async def test_start_binds_main_loop_to_review_callback(db_session: AsyncSession) -> None:
    callback = ReviewCallbackStub()
    factory = ConnectionFactoryStub()
    supervisor = FeishuBotSupervisor(
        _factory(db_session), _secret_box(), connection_factory=factory, review_callback=callback
    )

    await supervisor.start()

    assert callback.bound_loops == [asyncio.get_running_loop()]


@pytest.mark.anyio
async def test_default_connection_factory_wires_review_callback_into_event_handler(
    db_session: AsyncSession,
) -> None:
    callback = ReviewCallbackStub()
    supervisor = FeishuBotSupervisor(_factory(db_session), _secret_box(), review_callback=callback)

    connection = supervisor._build_default_connection(FeishuBotCredentials(app_id="cli_test", app_secret="s"))

    assert isinstance(connection, LarkWsConnection)
    event_handler = connection._client._event_handler
    assert "p2.im.message.receive_v1" in event_handler._processorMap
    assert "p2.card.action.trigger" in event_handler._callback_processor_map


@pytest.mark.anyio
async def test_default_connection_factory_without_review_callback_registers_only_im(
    db_session: AsyncSession,
) -> None:
    supervisor = FeishuBotSupervisor(_factory(db_session), _secret_box())

    connection = supervisor._build_default_connection(FeishuBotCredentials(app_id="cli_test", app_secret="s"))

    event_handler = connection._client._event_handler
    assert "p2.im.message.receive_v1" in event_handler._processorMap
    assert "p2.card.action.trigger" not in event_handler._callback_processor_map


def test_credentials_repr_hides_secrets() -> None:
    credentials = FeishuBotCredentials(app_id="cli_test", app_secret="s3cret-bot-value")

    text = repr(credentials)
    assert "s3cret-bot-value" not in text
    assert "cli_test" not in text
