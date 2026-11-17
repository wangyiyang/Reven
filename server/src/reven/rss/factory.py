"""Production adapters for the daily RSS discovery workflow."""

from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.config import Settings
from reven.notifications import DeliveryNotifier
from reven.provider_clients import ProviderClients
from reven.rss.bitable_store import BitableCandidateStore
from reven.rss.bitable_writer import BitableCandidateWriter
from reven.rss.discovery import EntryLocalizer, FeedEntry, FetchedEntry, LocalizedEntry, RssDiscoveryService
from reven.rss.embedding import (
    BGE_M3_DIMENSION,
    BGE_M3_MODEL,
    EmbeddingError,
    EmbedOutcome,
    KeywordEmbeddingService,
)
from reven.rss.feed import SecureFeedReader
from reven.rss.models import RssDiscoveryRun
from reven.rss.scheduler import RssScheduleTick
from reven.rss.screening import BoundaryJudge, RssScreeningEngine
from reven.rss.screening_service import RssScreeningService
from reven.rss.translation import configured_translation_localizer


class _UnavailableSiliconFlow:
    model = BGE_M3_MODEL
    dimension = BGE_M3_DIMENSION

    async def embed(self, texts: tuple[str, ...]) -> EmbedOutcome:
        raise EmbeddingError("EMBEDDING_NOT_CONFIGURED", "Embedding 服务未配置")

    async def localize(self, entries: tuple[FeedEntry, ...]) -> tuple[LocalizedEntry, ...]:
        raise RuntimeError("SILICONFLOW_API_KEY_NOT_CONFIGURED")


class RssCandidatePipeline:
    """内存筛选 → 候选直写 Bitable 的 run 阶段组合；任一失败向上抛（= run 失败，可整体重试）。"""

    def __init__(self, screening: RssScreeningService, writer: BitableCandidateWriter) -> None:
        self._screening = screening
        self._writer = writer

    async def screen_run(self, run_id: UUID, entries: tuple[FetchedEntry, ...]) -> int:
        candidates = await self._screening.screen_run(entries)
        return await self._writer.write_candidates(run_id=run_id, candidates=candidates)


class RssDiscoveryJob:
    """每日 RSS 发现任务：外部客户端经 ProviderClients seam 获取，未配置时按既有语义降级。

    同日完成缓存（notification_sent_at 为准）；failed 状态的 run 视为未完成，下个 tick 整体重试。
    """

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        clients: ProviderClients,
        settings: Settings,
        notifier: DeliveryNotifier,
    ) -> None:
        self._factory = factory
        self._clients = clients
        self._settings = settings
        self._notifier = notifier
        self._completed_date: date | None = None

    async def __call__(self) -> None:
        await RssScheduleTick(self)()

    async def run(self, run_date: date) -> object:
        if self._completed_date == run_date:
            return None
        pending = BitableCandidateStore(self._factory, self._clients)
        if await self._finalized(run_date):
            result = await RssDiscoveryService(
                self._factory,
                SecureFeedReader(),
                _UnavailableSiliconFlow(),
                self._notifier,
                candidate_url=f"{self._settings.public_base_url}/rss/candidates",
                pending_counter=pending.count_candidates,
                translation_alert_count=self._settings.rss_translation_alert_count,
                translation_alert_ratio=self._settings.rss_translation_alert_ratio,
                source_max_consecutive_failures=self._settings.rss_source_max_consecutive_failures,
            ).run(run_date)
            await self._remember_completion(run_date)
            return result
        translation_configs = await self._clients.credentials.translations()
        async with self._clients.siliconflow_chat() as chat:
            fallback: EntryLocalizer = chat if chat is not None else _UnavailableSiliconFlow()
            judge: BoundaryJudge | None = chat if chat is not None and self._settings.rss_model_review_enabled else None
            async with configured_translation_localizer(translation_configs, fallback) as localizer:
                async with self._clients.embedding() as embedder:
                    embeddings = KeywordEmbeddingService(
                        self._factory,
                        embedder if embedder is not None else _UnavailableSiliconFlow(),
                    )
                    pipeline = RssCandidatePipeline(
                        RssScreeningService(
                            self._factory,
                            embeddings,
                            RssScreeningEngine(judge=judge),
                        ),
                        BitableCandidateWriter(self._factory, self._clients),
                    )
                    discovery = RssDiscoveryService(
                        self._factory,
                        SecureFeedReader(),
                        localizer,
                        self._notifier,
                        screener=pipeline,
                        candidate_url=f"{self._settings.public_base_url}/rss/candidates",
                        pending_counter=pending.count_candidates,
                        translation_alert_count=self._settings.rss_translation_alert_count,
                        translation_alert_ratio=self._settings.rss_translation_alert_ratio,
                        source_max_consecutive_failures=self._settings.rss_source_max_consecutive_failures,
                    )
                    result = await discovery.run(run_date)
        await self._remember_completion(run_date)
        return result

    async def _finalized(self, run_date: date) -> bool:
        """failed 不是终态：候选写入失败的 run 由后续 tick 重试（重跑入口重置 checkpoint）。"""
        async with self._factory() as session:
            status = await session.scalar(select(RssDiscoveryRun.status).where(RssDiscoveryRun.run_date == run_date))
        return status is not None and status not in {"running", "screening", "failed"}

    async def _remember_completion(self, run_date: date) -> None:
        async with self._factory() as session:
            sent_at = await session.scalar(
                select(RssDiscoveryRun.notification_sent_at).where(RssDiscoveryRun.run_date == run_date)
            )
        if sent_at is not None:
            self._completed_date = run_date


class KeywordEmbeddingRefresher:
    """关键词向量重建：embedding 客户端由 ProviderClients seam 提供；未配置时报错由路由映射 503。"""

    def __init__(self, factory: async_sessionmaker[AsyncSession], clients: ProviderClients | None) -> None:
        self._factory = factory
        self._clients = clients

    async def refresh(self, *, force: bool = False) -> int:
        if self._clients is None:
            raise RuntimeError("SILICONFLOW_API_KEY_NOT_CONFIGURED")
        async with self._clients.embedding() as embedder:
            if embedder is None:
                raise RuntimeError("SILICONFLOW_API_KEY_NOT_CONFIGURED")
            return await KeywordEmbeddingService(self._factory, embedder).refresh(force=force)
