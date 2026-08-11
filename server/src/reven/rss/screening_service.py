"""Persist explainable screening outcomes while keeping item vectors ephemeral."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.rss.embedding import KeywordEmbeddingService
from reven.rss.models import RssDiscoveryRun, RssItem, RssKeyword
from reven.rss.screening import KeywordSignal, RssScreeningEngine, ScreeningDecision, ScreeningDocument
from reven.scheduling import utc_now


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
        embedding_error: str | None = None
        try:
            await self._embeddings.refresh()
        except Exception as exc:
            embedding_error = type(exc).__name__
        documents, keywords = await self._inputs(run_id, include_vectors=embedding_error is None)
        if not documents:
            return await self._candidate_count(run_id)
        if embedding_error is None:
            try:
                vectors = await self._embeddings.embed_temporary(
                    tuple(f"{document.title}\n{document.summary}" for document in documents)
                )
            except Exception as exc:
                embedding_error = type(exc).__name__
                keywords = tuple(KeywordSignal(keyword.term, keyword.kind, None) for keyword in keywords)
                vectors = tuple(() for _document in documents)
        else:
            vectors = tuple(() for _document in documents)
        decisions = await self._engine.screen(documents, keywords, vectors)
        return await self._persist(run_id, decisions, embedding_error=embedding_error)

    async def _inputs(
        self,
        run_id: UUID,
        *,
        include_vectors: bool,
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
            keyword_rows = list(
                (
                    await session.scalars(
                        select(RssKeyword).where(RssKeyword.enabled.is_(True)).order_by(RssKeyword.id)
                    )
                ).all()
            )
        documents = tuple(ScreeningDocument(item.id, item.title_zh, item.summary_zh) for item in items)
        keywords = tuple(
            KeywordSignal(
                keyword.term,
                keyword.kind,
                tuple(keyword.embedding) if include_vectors and keyword.embedding is not None else None,
            )
            for keyword in keyword_rows
        )
        return documents, keywords

    async def _persist(
        self,
        run_id: UUID,
        decisions: tuple[ScreeningDecision, ...],
        *,
        embedding_error: str | None,
    ) -> int:
        candidate_count = sum(decision.status == "candidate" for decision in decisions)
        async with self._factory.begin() as session:
            for decision in decisions:
                item = await session.get(RssItem, decision.item_id, with_for_update=True)
                if item is None or item.status != "pending":
                    continue
                _apply_decision(item, decision, embedding_error=embedding_error)
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


def _apply_decision(item: RssItem, decision: ScreeningDecision, *, embedding_error: str | None) -> None:
    item.status = decision.status
    item.positive_literal_matches = list(decision.positive_literal_matches)
    item.negative_literal_matches = list(decision.negative_literal_matches)
    item.bm25_score = decision.bm25_score
    item.positive_embedding_score = decision.positive_embedding_score
    item.negative_embedding_score = decision.negative_embedding_score
    item.embedding_model = "BAAI/bge-m3" if embedding_error is None else None
    item.embedding_status = "completed" if embedding_error is None else "degraded"
    item.model_status = decision.model_status
    item.model_score = decision.model_score
    item.reason = decision.reason
    item.rules_version = decision.rules_version
    item.screening_error = embedding_error
    item.screened_at = utc_now()
