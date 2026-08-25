"""Production adapters for the daily RSS discovery workflow."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.config import Settings
from reven.integrations.embedding.configuration import EmbeddingConfig, load_embedding_config
from reven.integrations.notion.client import NotionClient
from reven.integrations.notion.configuration import IntegrationConfigurationError, load_notion_inbox_config
from reven.integrations.notion.models import NotionError
from reven.integrations.notion.service import NOTION_BASE_URL, REQUEST_TIMEOUT
from reven.publishing.notifications import DeliveryNotifier
from reven.rss.ai import SiliconFlowChatClient
from reven.rss.discovery import EntryLocalizer, FeedEntry, LocalizedEntry, RssDiscoveryService
from reven.rss.embedding import (
    BGE_M3_DIMENSION,
    BGE_M3_MODEL,
    Embedder,
    EmbeddingError,
    EmbedOutcome,
    KeywordEmbeddingService,
    SiliconFlowEmbeddingClient,
)
from reven.rss.feed import SecureFeedReader
from reven.rss.inbox import InboxPushError, InboxPushResult, RssInboxService
from reven.rss.models import RssDiscoveryRun
from reven.rss.scheduler import RssScheduleTick
from reven.rss.screening import BoundaryJudge, RssScreeningEngine
from reven.rss.screening_service import RssScreeningService

SILICONFLOW_BASE_URL = "https://api.siliconflow.cn"
SILICONFLOW_TIMEOUT = httpx.Timeout(45.0)


class _UnavailableSiliconFlow:
    model = BGE_M3_MODEL
    dimension = BGE_M3_DIMENSION

    async def embed(self, texts: tuple[str, ...]) -> EmbedOutcome:
        raise EmbeddingError("EMBEDDING_NOT_CONFIGURED", "Embedding 服务未配置")

    async def localize(self, entries: tuple[FeedEntry, ...]) -> tuple[LocalizedEntry, ...]:
        raise RuntimeError("SILICONFLOW_API_KEY_NOT_CONFIGURED")


@asynccontextmanager
async def configured_embedder(config: EmbeddingConfig | None) -> AsyncIterator[Embedder]:
    """按入库配置（或环境变量回退）创建 embedder；未配置时降级为显式报错实现。"""
    if config is None:
        yield _UnavailableSiliconFlow()
        return
    async with httpx.AsyncClient(base_url=config.base_url, timeout=SILICONFLOW_TIMEOUT, trust_env=False) as http:
        yield SiliconFlowEmbeddingClient(config.api_key, http=http, model=config.model)


async def record_backfill_error(
    factory: async_sessionmaker[AsyncSession],
    run_id: UUID,
    error_type: str,
) -> None:
    """回填失败时把错误挂到本次 run 上，与 discovery._screen 的语义一致。"""
    async with factory.begin() as session:
        run = await session.get(RssDiscoveryRun, run_id, with_for_update=True)
        if run is None:
            return
        run.errors = [*run.errors, {"stage": "backfill", "error_type": error_type}]
        run.failure_count += 1
        run.status = "partial"


class ConfiguredRssDiscoveryTick:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        notifier: DeliveryNotifier,
    ) -> None:
        self._factory = factory
        self._settings = settings
        self._notifier = notifier
        self._completed_date: date | None = None

    async def __call__(self) -> None:
        await RssScheduleTick(self)()

    async def run(self, run_date: date) -> object:
        if self._completed_date == run_date:
            return None
        if await self._finalized(run_date):
            unavailable = _UnavailableSiliconFlow()
            result = await RssDiscoveryService(
                self._factory,
                SecureFeedReader(),
                unavailable,
                self._notifier,
                candidate_url=f"{self._settings.public_base_url}/rss/candidates",
            ).run(run_date)
            await self._remember_completion(run_date)
            return result
        api_key = (
            self._settings.siliconflow_api_key.get_secret_value()
            if self._settings.siliconflow_api_key is not None
            else None
        )
        embedding_config = await load_embedding_config(self._factory)
        async with httpx.AsyncClient(
            base_url=SILICONFLOW_BASE_URL,
            timeout=SILICONFLOW_TIMEOUT,
            trust_env=False,
        ) as chat_http:
            localizer: EntryLocalizer
            judge: BoundaryJudge | None
            if api_key is None:
                localizer = _UnavailableSiliconFlow()
                judge = None
            else:
                localizer = SiliconFlowChatClient(
                    api_key,
                    model=self._settings.siliconflow_chat_model,
                    http=chat_http,
                )
                judge = localizer if self._settings.rss_model_review_enabled else None
            async with configured_embedder(embedding_config) as embedder:
                embeddings = KeywordEmbeddingService(self._factory, embedder)
                screening = RssScreeningService(
                    self._factory,
                    embeddings,
                    RssScreeningEngine(judge=judge),
                )
                discovery = RssDiscoveryService(
                    self._factory,
                    SecureFeedReader(),
                    localizer,
                    self._notifier,
                    screener=screening,
                    candidate_url=f"{self._settings.public_base_url}/rss/candidates",
                )
                result = await discovery.run(run_date)
                await self._backfill_degraded(screening, result.run_id)
        await self._remember_completion(run_date)
        return result

    async def _backfill_degraded(self, screening: RssScreeningService, run_id: UUID) -> None:
        """每日任务顺带补历史 degraded 条目；失败只记录，不影响主流程。"""
        try:
            await screening.rescreen_degraded()
        except Exception as exc:
            code = exc.code if isinstance(exc, EmbeddingError) else type(exc).__name__
            await record_backfill_error(self._factory, run_id, code)

    async def _finalized(self, run_date: date) -> bool:
        async with self._factory() as session:
            status = await session.scalar(select(RssDiscoveryRun.status).where(RssDiscoveryRun.run_date == run_date))
        return status is not None and status not in {"running", "screening"}

    async def _remember_completion(self, run_date: date) -> None:
        async with self._factory() as session:
            sent_at = await session.scalar(
                select(RssDiscoveryRun.notification_sent_at).where(RssDiscoveryRun.run_date == run_date)
            )
        if sent_at is not None:
            self._completed_date = run_date


class ConfiguredRssInboxPusher:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def push(self, item_id: UUID) -> InboxPushResult:
        try:
            token, inbox_data_source_id = await load_notion_inbox_config(self._factory)
        except IntegrationConfigurationError as exc:
            raise InboxPushError(exc.code, "Notion Inbox 尚未正确配置") from exc
        try:
            async with httpx.AsyncClient(
                base_url=NOTION_BASE_URL,
                timeout=REQUEST_TIMEOUT,
                trust_env=False,
            ) as http:
                return await RssInboxService(
                    self._factory,
                    NotionClient(token, http),
                    inbox_data_source_id,
                ).push(item_id)
        except InboxPushError:
            raise
        except NotionError as exc:
            raise InboxPushError("NOTION_INBOX_UNAVAILABLE", "Notion Inbox 暂时不可用", status_code=503) from exc
        except httpx.HTTPError as exc:
            raise InboxPushError("NOTION_INBOX_UNAVAILABLE", "Notion Inbox 暂时不可用", status_code=503) from exc


class ConfiguredKeywordEmbeddingRefresher:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def refresh(self, *, force: bool = False) -> int:
        config = await load_embedding_config(self._factory)
        if config is None:
            raise RuntimeError("SILICONFLOW_API_KEY_NOT_CONFIGURED")
        async with httpx.AsyncClient(
            base_url=config.base_url,
            timeout=SILICONFLOW_TIMEOUT,
            trust_env=False,
        ) as http:
            embedder = SiliconFlowEmbeddingClient(config.api_key, http=http, model=config.model)
            return await KeywordEmbeddingService(self._factory, embedder).refresh(force=force)


def build_configured_rss_tick(
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    notifier: DeliveryNotifier,
) -> ConfiguredRssDiscoveryTick:
    return ConfiguredRssDiscoveryTick(factory, settings, notifier)
