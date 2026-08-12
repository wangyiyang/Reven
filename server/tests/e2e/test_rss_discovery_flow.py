from datetime import UTC, date, datetime

import pytest
from reven.rss.discovery import FeedEntry, LocalizedEntry, RssDiscoveryService
from reven.rss.embedding import BGE_M3_DIMENSION, BGE_M3_MODEL, KeywordEmbeddingService
from reven.rss.inbox import RssInboxService
from reven.rss.models import RssItem, RssSource
from reven.rss.repository import RssSettingsRepository
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

    async def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        vector = tuple([1.0] + [0.0] * (self.dimension - 1))
        return tuple(vector for _text in texts)


class Notifier:
    def __init__(self) -> None:
        self.messages: list[object] = []

    async def send(self, message: object) -> None:
        self.messages.append(message)


class Notion:
    def __init__(self) -> None:
        self.pages: list[dict[str, object]] = []

    async def retrieve_data_source(self, data_source_id: str) -> dict[str, object]:
        return {"properties": {"来源": {"type": "rich_text"}}}

    async def query_data_source(self, data_source_id: str, *, filter: dict[str, object]) -> dict[str, object]:
        item_id = filter["rich_text"]["equals"]  # type: ignore[index]
        matches = [page for page in self.pages if page["reven_id"] == item_id]
        return {"results": matches}

    async def create_page(self, data_source_id: str, *, properties: dict[str, object]) -> dict[str, object]:
        page = {
            "id": "55555555-5555-5555-5555-555555555555",
            "url": "https://www.notion.so/material",
            "reven_id": properties["Reven ID"]["rich_text"][0]["text"]["content"],  # type: ignore[index]
            "properties": properties,
        }
        self.pages.append(page)
        return page


@pytest.mark.anyio
async def test_rss_discovery_to_human_confirmed_notion_inbox_is_idempotent(
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
        candidate_url="https://reven.example/rss/candidates",
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

    notion = Notion()
    inbox = RssInboxService(factory, notion, "inbox")
    pushed = await inbox.push(candidate_id)
    repeated = await inbox.push(candidate_id)

    assert first.run_id == second.run_id
    assert first.candidate_count == 1
    assert len(notifier.messages) == 1
    assert pushed == repeated
    assert len(notion.pages) == 1
    properties = notion.pages[0]["properties"]
    assert properties["名称"]["title"][0]["text"]["content"] == "AI 智能体架构"  # type: ignore[index]
    assert "reason" not in properties and "bm25_score" not in properties  # type: ignore[operator]
