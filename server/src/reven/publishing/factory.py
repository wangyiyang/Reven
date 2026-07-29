"""生产环境交付编排器装配。"""

from pathlib import Path

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.config import Settings
from reven.domain import JobStatus, TargetChannel
from reven.integrations.feishu.client import FeishuWebhookClient, NotificationCard
from reven.integrations.notion.client import NotionClient
from reven.integrations.notion.configuration import (
    IntegrationConfigurationError,
    load_notion_config,
)
from reven.integrations.notion.models import NotionConfigError, NotionTransientError
from reven.integrations.notion.service import NOTION_BASE_URL, REQUEST_TIMEOUT
from reven.integrations.repository import IntegrationRepository
from reven.jobs.errors import BlockedPublishError, TransientPublishError
from reven.publishing.blog.factory import ConfiguredBlogPublisher
from reven.publishing.delivery_store import SqlAlchemyDeliveryStore
from reven.publishing.orchestrator import (
    DeliveryRecord,
    Notification,
    PublicationOrchestrator,
)
from reven.publishing.wechat.factory import ConfiguredWeChatPublisher
from reven.security.secrets import SecretBox, SecretBoxError


class ConfiguredNotionDeliveryWriter:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def write(
        self,
        record: DeliveryRecord,
        status: JobStatus,
        reason: str,
    ) -> None:
        try:
            token, _source = await load_notion_config(self.session_factory)
            async with httpx.AsyncClient(
                base_url=NOTION_BASE_URL,
                timeout=REQUEST_TIMEOUT,
                trust_env=False,
            ) as http:
                await NotionClient(token, http).update_page(
                    record.notion_page_id,
                    properties=_notion_properties(record, status, reason),
                )
        except (NotionTransientError, httpx.HTTPError) as exc:
            raise TransientPublishError("Notion 交付状态暂时无法回写") from exc
        except (IntegrationConfigurationError, NotionConfigError) as exc:
            raise BlockedPublishError("Notion 配置无效，交付状态无法回写") from exc


class ConfiguredFeishuNotifier:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        secret_box: SecretBox,
    ) -> None:
        self.session_factory = session_factory
        self.secret_box = secret_box

    async def send(self, notification: Notification) -> None:
        webhook_url = await self._webhook_url()
        async with httpx.AsyncClient(timeout=10, trust_env=False) as http:
            await FeishuWebhookClient(webhook_url, http=http).send(
                NotificationCard(
                    notification.title,
                    str(notification.stage),
                    notification.summary,
                    notification.links,
                )
            )

    async def _webhook_url(self) -> str:
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
        return webhook_url


def build_configured_orchestrator(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> PublicationOrchestrator:
    data_root = Path(settings.job_data_dir)
    secret_box = SecretBox.from_base64(settings.reven_master_key.get_secret_value())
    return PublicationOrchestrator(
        SqlAlchemyDeliveryStore(
            session_factory,
            data_root,
            settings.public_base_url,
        ),
        ConfiguredBlogPublisher(session_factory, secret_box, data_root),
        ConfiguredWeChatPublisher(
            session_factory,
            secret_box,
            data_root,
            settings.renderer_command,
        ),
        ConfiguredNotionDeliveryWriter(session_factory),
        ConfiguredFeishuNotifier(session_factory, secret_box),
    )


def _notion_properties(
    record: DeliveryRecord,
    status: JobStatus,
    reason: str,
) -> dict[str, object]:
    if status == JobStatus.COMPLETED:
        properties: dict[str, object] = {
            "状态": {"status": {"name": "已交付"}},
            "自动化状态": {"select": {"name": "已完成"}},
            "失败原因": {"rich_text": []},
        }
        blog_url = record.channel_results.get(TargetChannel.BLOG, {}).get("article_url")
        if isinstance(blog_url, str):
            properties["链接"] = {"url": blog_url}
        return properties
    automation = "阻塞" if status == JobStatus.BLOCKED else "失败"
    return {
        "自动化状态": {"select": {"name": automation}},
        "失败原因": {"rich_text": [{"text": {"content": reason[:2000]}}]},
    }
