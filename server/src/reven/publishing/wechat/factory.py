import shlex
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.articles.models import Article
from reven.integrations.notion.client import NotionClient
from reven.integrations.repository import IntegrationRepository
from reven.integrations.service import public_config_without_hint
from reven.integrations.wechat.client import WeChatClient
from reven.jobs.errors import BlockedPublishError
from reven.jobs.models import PublicationJob
from reven.jobs.repository import JobClaim
from reven.publishing.assets import AssetMaterializer
from reven.publishing.wechat.images import SnapshotAssetRecoverer
from reven.publishing.wechat.publisher import (
    SqlAlchemyWeChatResultStore,
    WeChatPublisher,
)
from reven.publishing.wechat.renderer import WechatRenderer
from reven.security.secrets import SecretBox, SecretBoxError


@dataclass(frozen=True)
class _Configuration:
    app_id: str
    app_secret: str
    author: str
    notion_token: str


class ConfiguredWeChatPublisher:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        secret_box: SecretBox,
        data_root: Path,
        renderer_command: str,
        *,
        wechat_transport: httpx.AsyncBaseTransport | None = None,
        notion_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.secret_box = secret_box
        self.data_root = data_root
        self.renderer_command = renderer_command
        self.wechat_transport = wechat_transport
        self.notion_transport = notion_transport

    async def publish(self, claim: JobClaim):  # type: ignore[no-untyped-def]
        config = await self._load_configuration()
        async with (
            httpx.AsyncClient(
                base_url="https://api.weixin.qq.com",
                transport=self.wechat_transport,
                trust_env=False,
            ) as wechat_http,
            httpx.AsyncClient(
                base_url="https://api.notion.com",
                transport=self.notion_transport,
                trust_env=False,
            ) as notion_http,
        ):
            notion = NotionClient(config.notion_token, notion_http)
            source: tuple[str, str | None] | None = None

            async def load_markdown() -> str:
                nonlocal source
                source = source or await self._source(claim.job_id, notion)
                return source[0]

            async def load_cover() -> str | None:
                nonlocal source
                source = source or await self._source(claim.job_id, notion)
                return source[1]

            recoverer = SnapshotAssetRecoverer(
                AssetMaterializer(self.data_root),
                load_markdown,
                load_cover,
            )
            executable, cli_path = _renderer_parts(self.renderer_command)
            publisher = WeChatPublisher(
                WeChatClient(config.app_id, config.app_secret, wechat_http),
                WechatRenderer(executable, cli_path),
                SqlAlchemyWeChatResultStore(
                    self.session_factory,
                    author=config.author,
                ),
                assets_recoverer=recoverer,
            )
            return await publisher.publish(claim)

    async def _load_configuration(self) -> _Configuration:
        async with self.session_factory() as session:
            repository = IntegrationRepository(session)
            wechat = await repository.get_by_provider("wechat")
            notion = await repository.get_by_provider("notion")
        if wechat is None or notion is None or wechat.encrypted_secret is None or notion.encrypted_secret is None:
            raise BlockedPublishError("微信或 Notion 集成尚未配置")
        try:
            wechat_secret = self.secret_box.decrypt(wechat.encrypted_secret)
            notion_secret = self.secret_box.decrypt(notion.encrypted_secret)
        except SecretBoxError as exc:
            raise BlockedPublishError("集成 Secret 无法解密，请重新配置") from exc
        public = public_config_without_hint(wechat)
        app_id = public.get("app_id")
        if not isinstance(app_id, str) or not app_id:
            raise BlockedPublishError("微信 AppID 尚未配置")
        app_secret = wechat_secret.get("app_secret")
        notion_token = notion_secret.get("token")
        if not app_secret or not notion_token:
            raise BlockedPublishError("微信或 Notion Secret 尚未配置")
        return _Configuration(
            app_id,
            app_secret,
            str(public.get("author", "")),
            notion_token,
        )

    async def _source(
        self,
        job_id: UUID,
        notion: NotionClient,
    ) -> tuple[str, str | None]:
        async with self.session_factory() as session:
            pair = (
                await session.execute(
                    select(PublicationJob, Article)
                    .join(Article, Article.id == PublicationJob.article_id)
                    .where(PublicationJob.id == job_id)
                )
            ).one_or_none()
        if pair is None:
            raise BlockedPublishError("发布任务不存在")
        _job, article = pair
        markdown = await notion.retrieve_page_markdown(article.notion_page_id)
        cover = article.cover_metadata.get("url")
        return markdown, cover if isinstance(cover, str) else None


class ConfiguredWeChatPublisherFactory:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        secret_box: SecretBox,
        data_root: Path,
        renderer_command: str,
    ) -> None:
        self.session_factory = session_factory
        self.secret_box = secret_box
        self.data_root = data_root
        self.renderer_command = renderer_command

    def build(self) -> ConfiguredWeChatPublisher:
        return ConfiguredWeChatPublisher(
            self.session_factory,
            self.secret_box,
            self.data_root,
            self.renderer_command,
        )


def _renderer_parts(command: str) -> tuple[str, str]:
    parts = shlex.split(command)
    if len(parts) != 2:
        raise BlockedPublishError("微信渲染器命令配置无效")
    return parts[0], parts[1]
