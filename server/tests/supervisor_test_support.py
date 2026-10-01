"""Supervisor 测试共享配置、连接与网络隔离 fixture。"""

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

    async def __aenter__(self) -> "FakeBotApiClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

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
