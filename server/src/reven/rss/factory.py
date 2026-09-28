"""Production adapters for the daily RSS discovery workflow."""

from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.config import Settings
from reven.notifications import DeliveryNotifier
from reven.provider_clients import ProviderClients
from reven.rss.discovery import EntryLocalizer, FeedEntry, LocalizedEntry, RssDiscoveryService
from reven.rss.embedding import (
    BGE_M3_DIMENSION,
    BGE_M3_MODEL,
    EmbeddingError,
    EmbedOutcome,
    KeywordEmbeddingService,
)
from reven.rss.feed import SecureFeedReader
from reven.rss.models import RssDiscoveryRun, RssItem, RssKeyword
from reven.rss.scheduler import RssScheduleTick
from reven.rss.screening import EMBEDDING_CANDIDATE_THRESHOLD, BoundaryJudge, RssScreeningEngine, cosine_similarity
from reven.rss.screening_service import RssScreeningService
from reven.rss.translation import configured_translation_localizer
from reven.scheduling import utc_now

# 命中数估计的检索窗口：与筛选同款的近期条目（条目向量不持久化，估计时临时重算，故限窗限量）
HIT_ESTIMATE_WINDOW_DAYS = 7
HIT_ESTIMATE_MAX_ITEMS = 300


class _UnavailableSiliconFlow:
    model = BGE_M3_MODEL
    dimension = BGE_M3_DIMENSION

    async def embed(self, texts: tuple[str, ...]) -> EmbedOutcome:
        raise EmbeddingError("EMBEDDING_NOT_CONFIGURED", "Embedding 服务未配置")

    async def localize(self, entries: tuple[FeedEntry, ...]) -> tuple[LocalizedEntry, ...]:
        raise RuntimeError("SILICONFLOW_API_KEY_NOT_CONFIGURED")


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


class RssDiscoveryJob:
    """每日 RSS 发现任务：外部客户端经 ProviderClients seam 获取，未配置时按既有语义降级。

    同日完成缓存（notification_sent_at 为准）与 degraded 回填失败只记录的语义保持不变。
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
        if await self._finalized(run_date):
            result = await RssDiscoveryService(
                self._factory,
                SecureFeedReader(),
                _UnavailableSiliconFlow(),
                self._notifier,
                candidate_url=f"{self._settings.public_base_url}/rss/candidates",
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

    async def estimate_hits(self, keyword_id: UUID) -> int | None:
        """估计关键词对近期条目库的语义命中数，复用筛选同款向量与 EMBEDDING_CANDIDATE_THRESHOLD 阈值。

        库为空返回 0；词向量缺失或 embedder 未配置返回 None（调用方据此降级话术，不抛出）。
        """
        if self._clients is None:
            return None
        cutoff = utc_now() - timedelta(days=HIT_ESTIMATE_WINDOW_DAYS)
        async with self._factory() as session:
            keyword = await session.get(RssKeyword, keyword_id)
            items = list(
                (
                    await session.scalars(
                        select(RssItem)
                        .where(RssItem.first_seen_at >= cutoff)
                        .order_by(RssItem.first_seen_at.desc())
                        .limit(HIT_ESTIMATE_MAX_ITEMS)
                    )
                ).all()
            )
        vector = tuple(keyword.embedding) if keyword is not None and keyword.embedding is not None else None
        if vector is None:
            return None
        if not items:
            return 0
        async with self._clients.embedding() as embedder:
            if embedder is None:
                return None
            outcome = await KeywordEmbeddingService(self._factory, embedder).embed_temporary(
                tuple(f"{item.title_zh}\n{item.summary_zh}" for item in items)
            )
        return sum(
            1
            for item_vector in outcome.vectors
            if item_vector is not None
            and len(item_vector) == len(vector)
            and cosine_similarity(item_vector, vector) >= EMBEDDING_CANDIDATE_THRESHOLD
        )
