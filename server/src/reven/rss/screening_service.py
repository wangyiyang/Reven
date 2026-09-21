"""Persist explainable screening outcomes while keeping item vectors ephemeral."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.rss.embedding import EmbeddingError, KeywordEmbeddingService
from reven.rss.models import RssDiscoveryRun, RssItem, RssKeyword
from reven.rss.screening import KeywordSignal, RssScreeningEngine, ScreeningDecision, ScreeningDocument
from reven.scheduling import utc_now

# 只允许回填仍处于机器决策状态的条目，人工已忽略/已保存的不动
_RESCREENABLE_STATUSES = ("candidate", "filtered")


class RssScreeningService:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        embeddings: KeywordEmbeddingService,
        engine: RssScreeningEngine,
    ) -> None:
        self._factory = factory
        self._embeddings = embeddings
        self._engine = engine

    async def screen_run(self, run_id: UUID) -> int:
        keyword_error: str | None = None
        try:
            await self._embeddings.refresh()
        except Exception as exc:
            keyword_error = _error_code(exc)
        documents, keywords = await self._inputs(run_id)
        if not documents:
            return await self._candidate_count(run_id)
        if keyword_error is None:
            item_codes: tuple[str | None, ...]
            vectors: tuple[tuple[float, ...], ...]
            try:
                outcome = await self._embeddings.embed_temporary(
                    tuple(f"{document.title}\n{document.summary}" for document in documents)
                )
            except Exception as exc:
                keyword_error = _error_code(exc)
                item_codes = tuple(keyword_error for _document in documents)
                vectors = tuple(() for _document in documents)
            else:
                vectors = tuple(vector if vector is not None else () for vector in outcome.vectors)
                item_codes = outcome.error_codes
        else:
            # 关键词向量不全时语义分不可信，整批保守降级
            vectors = tuple(() for _document in documents)
            item_codes = tuple(keyword_error for _document in documents)
        decisions = await self._engine.screen(documents, keywords, vectors)
        return await self._persist(run_id, decisions, item_codes=item_codes)

    async def rescreen_degraded(self, *, limit: int = 200) -> int:
        """重新打分历史上的 degraded 条目，返回实际更新的条数。"""
        documents = await self._degraded_documents(limit)
        if not documents:
            return 0
        await self._embeddings.refresh()
        keywords = await self._keyword_signals()
        outcome = await self._embeddings.embed_temporary(
            tuple(f"{document.title}\n{document.summary}" for document in documents)
        )
        vectors = tuple(vector if vector is not None else () for vector in outcome.vectors)
        decisions = await self._engine.screen(documents, keywords, vectors)
        updated = 0
        async with self._factory.begin() as session:
            for decision, code in zip(decisions, outcome.error_codes, strict=True):
                item = await session.get(RssItem, decision.item_id, with_for_update=True)
                if item is None or item.status not in _RESCREENABLE_STATUSES:
                    continue
                _apply_decision(item, decision, code=code, model=self._embeddings.model)
                updated += 1
        return updated

    async def _degraded_documents(self, limit: int) -> tuple[ScreeningDocument, ...]:
        async with self._factory() as session:
            items = list(
                (
                    await session.scalars(
                        select(RssItem)
                        .where(
                            RssItem.embedding_status == "degraded",
                            RssItem.status.in_(_RESCREENABLE_STATUSES),
                        )
                        .order_by(RssItem.first_seen_at)
                        .limit(limit)
                    )
                ).all()
            )
        return tuple(ScreeningDocument(item.id, item.title_zh, item.summary_zh) for item in items)

    async def _keyword_signals(self) -> tuple[KeywordSignal, ...]:
        async with self._factory() as session:
            keyword_rows = list(
                (
                    await session.scalars(
                        select(RssKeyword).where(RssKeyword.enabled.is_(True)).order_by(RssKeyword.id)
                    )
                ).all()
            )
        return tuple(
            KeywordSignal(
                keyword.term,
                keyword.kind,
                tuple(keyword.embedding) if keyword.embedding is not None else None,
            )
            for keyword in keyword_rows
        )

    async def _inputs(
        self,
        run_id: UUID,
    ) -> tuple[tuple[ScreeningDocument, ...], tuple[KeywordSignal, ...]]:
        async with self._factory() as session:
            items = list(
                (
                    await session.scalars(
                        select(RssItem)
                        .where(RssItem.first_seen_run_id == run_id, RssItem.status == "pending")
                        .order_by(RssItem.id)
                    )
                ).all()
            )
        documents = tuple(ScreeningDocument(item.id, item.title_zh, item.summary_zh) for item in items)
        return documents, await self._keyword_signals()

    async def _persist(
        self,
        run_id: UUID,
        decisions: tuple[ScreeningDecision, ...],
        *,
        item_codes: tuple[str | None, ...],
    ) -> int:
        candidate_count = sum(decision.status == "candidate" for decision in decisions)
        async with self._factory.begin() as session:
            for decision, code in zip(decisions, item_codes, strict=True):
                item = await session.get(RssItem, decision.item_id, with_for_update=True)
                if item is None or item.status != "pending":
                    continue
                _apply_decision(item, decision, code=code, model=self._embeddings.model)
            run = await session.get(RssDiscoveryRun, run_id, with_for_update=True)
            if run is None:
                raise RuntimeError("RSS 任务记录不存在")
            run.candidate_count = candidate_count
        return candidate_count

    async def _candidate_count(self, run_id: UUID) -> int:
        async with self._factory() as session:
            run = await session.get(RssDiscoveryRun, run_id)
            if run is None:
                raise RuntimeError("RSS 任务记录不存在")
            return run.candidate_count


def _error_code(exc: Exception) -> str:
    return exc.code if isinstance(exc, EmbeddingError) else type(exc).__name__


def _apply_decision(item: RssItem, decision: ScreeningDecision, *, code: str | None, model: str) -> None:
    item.status = decision.status
    item.positive_literal_matches = list(decision.positive_literal_matches)
    item.negative_literal_matches = list(decision.negative_literal_matches)
    item.bm25_score = decision.bm25_score
    item.positive_embedding_score = decision.positive_embedding_score
    item.negative_embedding_score = decision.negative_embedding_score
    item.embedding_model = model if code is None else None
    item.embedding_status = "completed" if code is None else "degraded"
    item.model_status = decision.model_status
    item.model_score = decision.model_score
    item.reason = decision.reason
    item.rules_version = decision.rules_version
    item.screening_error = code
    item.screened_at = utc_now()
