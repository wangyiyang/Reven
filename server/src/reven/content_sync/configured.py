"""Production adapters for the content-sync worker."""

from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.config import Settings
from reven.content_sync.downloader import SecureContentDownloader
from reven.content_sync.executor import (
    ArchivedContent,
    ContentSyncFailure,
    ContentSyncWorker,
    SourceDocument,
)
from reven.content_sync.gate import SnapshotAssetView
from reven.content_sync.media_archive import ContentMediaArchive
from reven.integrations.notion.client import NotionClient
from reven.integrations.notion.configuration import IntegrationConfigurationError, load_notion_config
from reven.integrations.notion.mapper import map_notion_page
from reven.integrations.notion.models import (
    NotionConfigError,
    NotionError,
    NotionFile,
    NotionSchemaError,
    NotionTransientError,
)
from reven.integrations.notion.service import NOTION_BASE_URL, REQUEST_TIMEOUT
from reven.integrations.tencent_cos.configuration import TencentCosConfigurationError
from reven.integrations.tencent_cos.store import build_tencent_cos_asset_store


class ConfiguredContentSource:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self.factory = factory

    async def load(self, page_id: str) -> SourceDocument:
        try:
            token, _ = await load_notion_config(self.factory)
            async with httpx.AsyncClient(base_url=NOTION_BASE_URL, timeout=REQUEST_TIMEOUT) as http:
                client = NotionClient(token=token, http=http)
                page = map_notion_page(await client.retrieve_page(page_id))
                markdown = await client.retrieve_page_markdown(page_id)
                return SourceDocument(page, markdown)
        except Exception as exc:
            raise _notion_failure(exc) from exc

    async def current_version(self, page_id: str) -> datetime:
        try:
            token, _ = await load_notion_config(self.factory)
            async with httpx.AsyncClient(base_url=NOTION_BASE_URL, timeout=REQUEST_TIMEOUT) as http:
                page = await NotionClient(token=token, http=http).retrieve_page(page_id)
                return map_notion_page(page).last_edited_at
        except Exception as exc:
            raise _notion_failure(exc) from exc


class ConfiguredMediaArchive:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.downloader = SecureContentDownloader(Path(settings.job_data_dir))

    async def archive(
        self,
        run_id: UUID,
        markdown: str,
        cover: NotionFile | None,
        *,
        progress: Callable[[str, int, int, str | None], Awaitable[None]] | None = None,
    ) -> ArchivedContent:
        try:
            store = build_tencent_cos_asset_store(self.settings)
        except TencentCosConfigurationError as exc:
            raise ContentSyncFailure("COS_NOT_CONFIGURED", "对象存储尚未正确配置") from exc
        try:
            return await ContentMediaArchive(self.downloader, store).archive(
                run_id,
                markdown,
                cover,
                progress=progress,
            )
        finally:
            await store.aclose()


class ConfiguredAssetIntegrityVerifier:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def verify(self, assets: tuple[SnapshotAssetView, ...]) -> None:
        try:
            store = build_tencent_cos_asset_store(self.settings)
        except TencentCosConfigurationError as exc:
            raise ContentSyncFailure("COS_NOT_CONFIGURED", "对象存储尚未正确配置") from exc
        try:
            for asset in assets:
                await store.verify(
                    asset.storage_key,
                    sha256=asset.sha256,
                    mime_type=asset.mime_type,
                    size=asset.byte_size,
                )
        finally:
            await store.aclose()


class ContentSyncTick:
    def __init__(self, worker: ContentSyncWorker) -> None:
        self.worker = worker

    async def __call__(self) -> None:
        await self.worker.run_once()


def build_content_sync_tick(
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> ContentSyncTick:
    worker = ContentSyncWorker(
        factory,
        ConfiguredContentSource(factory),
        ConfiguredMediaArchive(settings),
        lease_seconds=settings.job_lease_seconds,
    )
    return ContentSyncTick(worker)


def _notion_failure(error: Exception) -> ContentSyncFailure:
    if isinstance(error, IntegrationConfigurationError):
        return ContentSyncFailure(error.code, "Notion 集成尚未正确配置")
    if isinstance(error, NotionTransientError):
        return ContentSyncFailure("NOTION_UNAVAILABLE", "Notion 暂时不可用，请稍后重试", retryable=True)
    if isinstance(error, (NotionConfigError, NotionSchemaError)):
        return ContentSyncFailure("NOTION_INVALID", str(error))
    if isinstance(error, NotionError):
        return ContentSyncFailure("NOTION_FAILED", "Notion 内容读取失败")
    return ContentSyncFailure("NOTION_UNEXPECTED", "Notion 内容读取发生未知错误", retryable=True)
