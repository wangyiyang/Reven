"""RssScreeningService 内存筛选契约：run 内条目进、候选分组出，不落 PG 条目。

- 关键词配置仍存 PG；embedding/关键词向量失败整批降级为字面 + BM25 信号；
- filtered 不返回（不落任何存储）；候选映射字段供 Bitable writer 消费。
"""

from datetime import UTC, datetime

import pytest
from reven.rss.discovery import FeedEntry, FetchedEntry, LocalizedEntry
from reven.rss.embedding import BGE_M3_DIMENSION, BGE_M3_MODEL, EmbedOutcome, KeywordEmbeddingService
from reven.rss.repository import RssSettingsRepository
from reven.rss.screening import RssScreeningEngine
from reven.rss.screening_service import RssScreeningService
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class DeterministicEmbedder:
    model = BGE_M3_MODEL
    dimension = BGE_M3_DIMENSION

    async def embed(self, texts: tuple[str, ...]) -> EmbedOutcome:
        return EmbedOutcome(
            tuple(tuple([1.0] + [0.0] * (self.dimension - 1)) for _text in texts),
            tuple(None for _text in texts),
        )


class FailingEmbedder:
    model = BGE_M3_MODEL
    dimension = BGE_M3_DIMENSION

    async def embed(self, texts: tuple[str, ...]) -> EmbedOutcome:
        raise RuntimeError("provider unavailable")


class NoCallEmbedder:
    model = BGE_M3_MODEL
    dimension = BGE_M3_DIMENSION

    async def embed(self, texts: tuple[str, ...]) -> EmbedOutcome:
        raise AssertionError("不应发起 embedding 调用")


def _fetched(dedupe_key: str, *, title_zh: str = "AI 智能体架构", summary_zh: str = "实用模式") -> FetchedEntry:
    entry = FeedEntry(
        guid=f"guid-{dedupe_key}",
        url=f"https://example.com/{dedupe_key}",
        title=f"title {dedupe_key}",
        summary="summary",
        published_at=datetime(2026, 8, 11, 1, tzinfo=UTC),
    )
    return FetchedEntry(
        source_name="Example",
        entry=entry,
        localized=LocalizedEntry(entry, title_zh, summary_zh),
        dedupe_key=dedupe_key,
    )


def _service(db_session: AsyncSession, embedder: object) -> RssScreeningService:
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    return RssScreeningService(factory, KeywordEmbeddingService(factory, embedder), RssScreeningEngine())  # type: ignore[arg-type]


@pytest.mark.anyio
async def test_screen_run_returns_candidates_with_writer_fields(db_session: AsyncSession) -> None:
    await RssSettingsRepository(db_session).create_keyword(term="AI 智能体", kind="positive", enabled=True)
    await db_session.commit()
    service = _service(db_session, DeterministicEmbedder())

    candidates = await service.screen_run((_fetched("url:key-1"),))

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.title == "AI 智能体架构"
    assert candidate.summary == "实用模式"
    assert candidate.source_name == "Example"
    assert candidate.url == "https://example.com/url:key-1"
    assert candidate.published_at == datetime(2026, 8, 11, 1, tzinfo=UTC)
    assert candidate.matched_keywords == ("AI 智能体",)
    assert candidate.dedupe_key == "url:key-1"


@pytest.mark.anyio
async def test_screen_run_filters_out_entries_without_positive_signal(db_session: AsyncSession) -> None:
    await RssSettingsRepository(db_session).create_keyword(term="具身智能", kind="positive", enabled=True)
    await db_session.commit()
    service = _service(db_session, DeterministicEmbedder())

    # 关键词向量 [1,0,...] 与条目向量同向 → embedding 命中候选
    embedding_hit = _fetched("url:embedding-hit", title_zh="天气", summary_zh="晴")
    candidates = await service.screen_run((embedding_hit,))
    assert [candidate.dedupe_key for candidate in candidates] == ["url:embedding-hit"]
    assert candidates[0].matched_keywords == ()

    # 字面/语义均无正向信号 → filtered，不返回
    class OrthogonalEmbedder:
        model = BGE_M3_MODEL
        dimension = BGE_M3_DIMENSION

        async def embed(self, texts: tuple[str, ...]) -> EmbedOutcome:
            # 关键词（refresh）取 [1,0,...]；条目取 [0,1,...] 正交 → 语义分 0
            vectors = tuple(
                tuple([1.0] + [0.0] * (self.dimension - 1))
                if text == "具身智能"
                else tuple([0.0, 1.0] + [0.0] * (self.dimension - 2))
                for text in texts
            )
            return EmbedOutcome(vectors, tuple(None for _text in texts))

    service = _service(db_session, OrthogonalEmbedder())
    candidates = await service.screen_run((_fetched("url:no-signal", title_zh="天气", summary_zh="晴"),))
    assert candidates == ()


@pytest.mark.anyio
async def test_screen_run_degrades_to_literal_when_embedding_fails(db_session: AsyncSession) -> None:
    await RssSettingsRepository(db_session).create_keyword(term="AI 智能体", kind="positive", enabled=True)
    await db_session.commit()
    service = _service(db_session, FailingEmbedder())

    candidates = await service.screen_run((_fetched("url:key-2"),))

    assert len(candidates) == 1
    assert candidates[0].matched_keywords == ("AI 智能体",)


@pytest.mark.anyio
async def test_screen_run_with_empty_entries_skips_embedding(db_session: AsyncSession) -> None:
    service = _service(db_session, NoCallEmbedder())

    assert await service.screen_run(()) == ()


@pytest.mark.anyio
async def test_screen_run_negative_literal_blocks_candidate(db_session: AsyncSession) -> None:
    await RssSettingsRepository(db_session).create_keyword(term="AI 智能体", kind="positive", enabled=True)
    await RssSettingsRepository(db_session).create_keyword(term="广告", kind="negative", enabled=True)
    await db_session.commit()
    service = _service(db_session, FailingEmbedder())

    # 无正向字面命中且命中反向词 → filtered（正向命中存在时负向不拦截，见 screening 引擎契约）
    candidates = await service.screen_run((_fetched("url:key-3", title_zh="广告 推广", summary_zh="软文"),))

    assert candidates == ()
