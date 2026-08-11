import hashlib
from datetime import date

import pytest
from reven.rss.embedding import BGE_M3_DIMENSION, BGE_M3_MODEL, KeywordEmbeddingService
from reven.rss.models import RssDiscoveryRun, RssItem, RssSource
from reven.rss.repository import RssSettingsRepository
from reven.rss.screening import RssScreeningEngine
from reven.rss.screening_service import RssScreeningService
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class DeterministicEmbedder:
    model = BGE_M3_MODEL
    dimension = BGE_M3_DIMENSION

    async def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        return tuple(tuple([1.0] + [0.0] * (self.dimension - 1)) for _text in texts)


class FailingEmbedder:
    model = BGE_M3_MODEL
    dimension = BGE_M3_DIMENSION

    async def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        raise RuntimeError("provider unavailable")


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@pytest.mark.anyio
async def test_screening_service_persists_derived_scores_but_not_item_vectors(
    db_session: AsyncSession,
) -> None:
    source = RssSource(name="Example", feed_url="https://example.com/feed", enabled=True)
    run = RssDiscoveryRun(run_date=date(2026, 8, 11))
    db_session.add_all([source, run])
    await db_session.flush()
    item = RssItem(
        source_id=source.id,
        first_seen_run_id=run.id,
        source_name=source.name,
        guid="one",
        url="https://example.com/one",
        url_key=digest("url-one"),
        guid_key=digest("guid-one"),
        title_key=digest("title-one"),
        title="AI agent architecture",
        summary="Practical patterns",
        title_zh="AI 智能体架构",
        summary_zh="实用模式",
    )
    db_session.add(item)
    await RssSettingsRepository(db_session).create_keyword(term="AI 智能体", kind="positive", enabled=True)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    embeddings = KeywordEmbeddingService(factory, DeterministicEmbedder())
    service = RssScreeningService(factory, embeddings, RssScreeningEngine())

    assert await service.screen_run(run.id) == 1

    async with factory() as session:
        stored = await session.get(RssItem, item.id)
        stored_run = await session.get(RssDiscoveryRun, run.id)
        assert stored is not None and stored_run is not None
        assert stored.status == "candidate"
        assert stored.positive_literal_matches == ["AI 智能体"]
        assert stored.bm25_score > 0
        assert stored.positive_embedding_score == 1.0
        assert stored.embedding_model == BGE_M3_MODEL
        assert stored.rules_version == "rss-v1"
        assert stored_run.candidate_count == 1
        assert "embedding" not in RssItem.__table__.columns


@pytest.mark.anyio
async def test_screening_degrades_to_literal_and_bm25_when_embedding_fails(
    db_session: AsyncSession,
) -> None:
    source = RssSource(name="Example", feed_url="https://example.com/feed-2", enabled=True)
    run = RssDiscoveryRun(run_date=date(2026, 8, 12))
    db_session.add_all([source, run])
    await db_session.flush()
    item = RssItem(
        source_id=source.id,
        first_seen_run_id=run.id,
        source_name=source.name,
        guid="two",
        url="https://example.com/two",
        url_key=digest("url-two"),
        guid_key=digest("guid-two"),
        title_key=digest("title-two"),
        title="AI agent architecture",
        summary="Practical patterns",
        title_zh="AI 智能体架构",
        summary_zh="实用模式",
    )
    db_session.add(item)
    await RssSettingsRepository(db_session).create_keyword(term="AI 智能体", kind="positive", enabled=True)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    service = RssScreeningService(
        factory,
        KeywordEmbeddingService(factory, FailingEmbedder()),
        RssScreeningEngine(),
    )

    assert await service.screen_run(run.id) == 1

    async with factory() as session:
        stored = await session.get(RssItem, item.id)
        assert stored is not None
        assert stored.status == "candidate"
        assert stored.positive_literal_matches == ["AI 智能体"]
        assert stored.embedding_status == "degraded"
        assert stored.screening_error == "RuntimeError"
