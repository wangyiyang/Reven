"""RSS 内存筛选：run 内抓取条目 → 候选分组（不落 PG 条目，向量依旧不持久化）。

- 输入为 discovery 收集的 FetchedEntry 内存列表（权威存储为 Bitable，不再查 rss_items）；
- 关键词配置仍存 PG（运维状态）；embedding 失败按既有语义降级为字面/BM25 信号；
- 只返回 candidate 分组（filtered 不落任何存储，历史重筛能力取消）。
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.rss.discovery import FetchedEntry
from reven.rss.embedding import EmbeddingError, KeywordEmbeddingService
from reven.rss.models import RssKeyword
from reven.rss.screening import KeywordSignal, RssScreeningEngine, ScreeningDecision, ScreeningDocument


@dataclass(frozen=True)
class ScreenedCandidate:
    """筛选通过的候选（内存态）：writer 据此映射 Bitable 固定字段。

    title/summary 为本地化后的中文展示文本（与候选工作台主展示口径一致）；
    dedupe_key 由 discovery 按 URL > GUID > 归一化标题优先级生成（基于原文，稳定）。
    """

    source_name: str
    title: str
    summary: str
    url: str | None
    published_at: datetime | None
    matched_keywords: tuple[str, ...]
    dedupe_key: str


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

    async def screen_run(self, entries: tuple[FetchedEntry, ...]) -> tuple[ScreenedCandidate, ...]:
        """内存筛选：返回 candidate 分组；embedding/关键词向量失败时整批按字面+BM25 降级。"""
        if not entries:
            return ()
        keyword_error: str | None = None
        try:
            await self._embeddings.refresh()
        except Exception as exc:
            keyword_error = _error_code(exc)
        keywords = await self._keyword_signals()
        documents = tuple(
            ScreeningDocument(_entry_ref(entry), entry.localized.title_zh, entry.localized.summary_zh)
            for entry in entries
        )
        vectors: tuple[tuple[float, ...], ...]
        if keyword_error is None:
            try:
                outcome = await self._embeddings.embed_temporary(
                    tuple(f"{document.title}\n{document.summary}" for document in documents)
                )
            except Exception:
                # 条目向量整体失败：语义分不可信，整批保守降级
                vectors = tuple(() for _document in documents)
            else:
                vectors = tuple(vector if vector is not None else () for vector in outcome.vectors)
        else:
            # 关键词向量不全时语义分不可信，整批保守降级
            vectors = tuple(() for _document in documents)
        decisions = await self._engine.screen(documents, keywords, vectors)
        by_ref = {document.item_id: entry for document, entry in zip(documents, entries, strict=True)}
        return tuple(
            _to_candidate(by_ref[decision.item_id], decision)
            for decision in decisions
            if decision.status == "candidate"
        )

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


def _error_code(exc: Exception) -> str:
    return exc.code if isinstance(exc, EmbeddingError) else type(exc).__name__


def _entry_ref(entry: FetchedEntry) -> UUID:
    """条目在筛选引擎内的确定性标识：由去重键派生（同键同 ref，稳定）。"""
    return uuid5(NAMESPACE_URL, f"reven:rss-candidate:{entry.dedupe_key}")


def _to_candidate(entry: FetchedEntry, decision: ScreeningDecision) -> ScreenedCandidate:
    return ScreenedCandidate(
        source_name=entry.source_name,
        title=entry.localized.title_zh,
        summary=entry.localized.summary_zh,
        url=entry.entry.url,
        published_at=entry.entry.published_at,
        matched_keywords=decision.positive_literal_matches,
        dedupe_key=entry.dedupe_key,
    )
