from datetime import UTC, date, datetime

import pytest
from reven.rss.discovery import FeedEntry, LocalizedEntry, RssDiscoveryService
from reven.rss.embedding import BGE_M3_DIMENSION, BGE_M3_MODEL, EmbedOutcome, KeywordEmbeddingService
from reven.rss.models import RssItem, RssSource
from reven.rss.repository import RssSettingsRepository
from reven.rss.review_service import CandidateReviewService
from reven.rss.screening import RssScreeningEngine
from reven.rss.screening_service import RssScreeningService
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class Feed:
    async def fetch(self, source: RssSource) -> tuple[FeedEntry, ...]:
        return (
            FeedEntry(
                "agent-1",
                "https://example.com/agent-1",
                "AI agent architecture",
                "Practical engineering patterns",
                datetime(2026, 8, 11, 1, tzinfo=UTC),
            ),
        )


class Localizer:
    async def localize(self, entries: tuple[FeedEntry, ...]) -> tuple[LocalizedEntry, ...]:
        return tuple(LocalizedEntry(entry, "AI 智能体架构", "实用工程模式") for entry in entries)


class Embedder:
    model = BGE_M3_MODEL
    dimension = BGE_M3_DIMENSION

    async def embed(self, texts: tuple[str, ...]) -> EmbedOutcome:
        vector = tuple([1.0] + [0.0] * (self.dimension - 1))
        return EmbedOutcome(tuple(vector for _text in texts), tuple(None for _text in texts))


class Notifier:
    def __init__(self) -> None:
        self.messages: list[object] = []

    async def send(self, message: object) -> None:
        self.messages.append(message)


@pytest.mark.anyio
async def test_rss_discovery_to_saved_material_is_idempotent(
    db_session: AsyncSession,
) -> None:
    source = RssSource(name="Example", feed_url="https://example.com/e2e.xml", enabled=True)
    db_session.add(source)
    await RssSettingsRepository(db_session).create_keyword(term="AI 智能体", kind="positive", enabled=True)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    notifier = Notifier()
    embeddings = KeywordEmbeddingService(factory, Embedder())
    screening = RssScreeningService(factory, embeddings, RssScreeningEngine())
    discovery = RssDiscoveryService(
        factory,
        Feed(),
        Localizer(),
        notifier,
        screener=screening,
        candidate_url="http://reven.example/rss/candidates",
    )

    first = await discovery.run(date(2026, 8, 11))
    second = await discovery.run(date(2026, 8, 11))
    async with factory() as session:
        candidate = await session.scalar(select(RssItem))
        assert candidate is not None
        candidate_id = candidate.id
        assert candidate.status == "candidate"
        assert candidate.positive_literal_matches == ["AI 智能体"]
        assert candidate.embedding_status == "completed"

    review = CandidateReviewService(factory)
    saved = await review.approve(candidate_id)
    repeated = await review.approve(candidate_id)

    assert first.run_id == second.run_id
    assert first.candidate_count == 1
    assert len(notifier.messages) == 1
    assert saved.id == repeated.id == candidate_id
    assert saved.saved_at is not None
    assert saved.saved_at == repeated.saved_at
    assert await review.list_pending_review() == []
    async with factory() as session:
        materials = list(await session.scalars(select(RssItem).where(RssItem.status == "saved")))
        assert len(materials) == 1
        material = materials[0]
        assert material.id == candidate_id
        assert material.saved_at == saved.saved_at
        assert material.title_zh == "AI 智能体架构"
        assert material.summary_zh == "实用工程模式"
        assert material.url == "https://example.com/agent-1"
