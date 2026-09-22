"""Shared notification contract and configured Feishu application bot delivery."""

from dataclasses import dataclass
from typing import Protocol

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.config import Settings
from reven.integrations.credentials import IntegrationCredentials
from reven.integrations.feishu_bot.client import FeishuBotApiClient


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
        credentials: IntegrationCredentials,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.credentials = credentials
        self.transport = transport

    async def send(self, notification: Notification) -> None:
        config = await self.credentials.feishu_bot()
        if config is None:
            raise RuntimeError("飞书应用机器人未启用或凭证不可用")
        client = FeishuBotApiClient(config.app_id, config.app_secret, transport=self.transport)
        lines = [notification.title, f"当前阶段：{notification.stage}", notification.summary]
        lines.extend(f"{label}：{url}" for label, url in notification.links.items())
        await client.send_text_to_recipients(config.whitelist_open_ids, "\n".join(lines))


def build_configured_notifier(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> ConfiguredFeishuNotifier:
    return ConfiguredFeishuNotifier(IntegrationCredentials(session_factory, settings))
