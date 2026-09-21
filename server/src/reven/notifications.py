"""Shared notification contract and configured Feishu webhook delivery."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.config import Settings
from reven.integrations.feishu.client import FeishuWebhookClient, NotificationCard
from reven.integrations.repository import IntegrationRepository
from reven.security.secrets import SecretBox, SecretBoxError


@dataclass(frozen=True)
class Notification:
    title: str
    stage: str
    summary: str
    links: dict[str, str]


class DeliveryNotifier(Protocol):
    async def send(self, notification: Notification) -> None: ...


class ConfiguredFeishuNotifier:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        secret_box: SecretBox,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.session_factory = session_factory
        self.secret_box = secret_box
        self.transport = transport
        self.clock = clock

    async def send(self, notification: Notification) -> None:
        webhook_url, signing_secret = await self._credentials()
        async with httpx.AsyncClient(timeout=10, trust_env=False, transport=self.transport) as http:
            await FeishuWebhookClient(
                webhook_url,
                http=http,
                signing_secret=signing_secret,
                clock=self.clock,
            ).send(
                NotificationCard(
                    notification.title,
                    str(notification.stage),
                    notification.summary,
                    notification.links,
                )
            )

    async def _credentials(self) -> tuple[str, str | None]:
        async with self.session_factory() as session:
            integration = await IntegrationRepository(session).get_by_provider("feishu")
        if integration is None or integration.encrypted_secret is None:
            raise RuntimeError("飞书集成尚未配置")
        try:
            secret = self.secret_box.decrypt(integration.encrypted_secret)
        except SecretBoxError as exc:
            raise RuntimeError("飞书 Secret 无法解密") from exc
        webhook_url = secret.get("webhook_url")
        if not webhook_url:
            raise RuntimeError("飞书 Webhook 尚未配置")
        return webhook_url, secret.get("signing_secret")


def build_configured_notifier(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> ConfiguredFeishuNotifier:
    secret_box = SecretBox.from_base64(settings.reven_master_key.get_secret_value())
    return ConfiguredFeishuNotifier(session_factory, secret_box)
