import hashlib
from datetime import date
from uuid import UUID

import pytest
from reven.rss.inbox import InboxPushError, RssInboxService
from reven.rss.models import RssDiscoveryRun, RssItem, RssSource
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

INBOX_ID = "44444444-4444-4444-4444-444444444444"
PAGE_ID = "55555555-5555-5555-5555-555555555555"


class RecordingNotion:
    def __init__(
        self,
        existing: dict[str, object] | None = None,
        *,
        page_url: str = "https://www.notion.so/material",
    ) -> None:
        self.existing = existing
        self.page_url = page_url
        self.queries: list[dict[str, object]] = []
        self.created: list[dict[str, object]] = []

    async def query_data_source(
        self,
        data_source_id: str,
        *,
        filter: dict[str, object],
    ) -> dict[str, object]:
        assert data_source_id == INBOX_ID
        self.queries.append(filter)
        return {"results": [self.existing] if self.existing else []}

    async def create_page(self, data_source_id: str, *, properties: dict[str, object]) -> dict[str, object]:
        assert data_source_id == INBOX_ID
        self.created.append(properties)
        return {"id": PAGE_ID, "url": self.page_url}


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


async def seed_candidate(session: AsyncSession, *, status: str = "candidate") -> RssItem:
    source = RssSource(name="Example", feed_url="https://example.com/feed", enabled=True)
    run = RssDiscoveryRun(run_date=date(2026, 8, 11))
    session.add_all([source, run])
    await session.flush()
    item = RssItem(
        source_id=source.id,
        first_seen_run_id=run.id,
        source_name=source.name,
        guid="one",
        url="https://example.com/one",
        url_key=digest("url-one"),
        guid_key=digest("guid-one"),
        title_key=digest("title-one"),
        title="Agent systems",
        summary="Original summary",
        title_zh="智能体系统",
        summary_zh="中文摘要",
        status=status,
        reason="高价值候选",
        positive_literal_matches=["agent"],
        positive_embedding_score=0.9,
    )
    session.add(item)
    await session.commit()
    return item


@pytest.mark.anyio
async def test_confirm_pushes_material_once_without_internal_scores(db_session: AsyncSession) -> None:
    item = await seed_candidate(db_session)
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    notion = RecordingNotion()
    service = RssInboxService(factory, notion, INBOX_ID)

    first = await service.push(item.id)
    second = await service.push(item.id)

    assert first == second
    assert first.notion_page_id == UUID(PAGE_ID)
    assert len(notion.queries) == 1
    assert len(notion.created) == 1
    properties = notion.created[0]
    assert set(properties) == {"名称", "Reven ID", "来源", "原文链接", "发布时间", "摘要"}
    serialized = repr(properties)
    assert "高价值候选" not in serialized
    assert "agent" not in serialized.casefold()
    assert "0.9" not in serialized
    async with factory() as session:
        stored = await session.get(RssItem, item.id)
        assert stored is not None
        assert stored.status == "pushed"
        assert stored.notion_page_id == UUID(PAGE_ID)


@pytest.mark.anyio
async def test_retry_adopts_existing_notion_page_after_ambiguous_interruption(db_session: AsyncSession) -> None:
    item = await seed_candidate(db_session, status="pushing")
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    notion = RecordingNotion({"id": PAGE_ID, "url": "https://www.notion.so/material"})

    result = await RssInboxService(factory, notion, INBOX_ID).push(item.id)

    assert result.notion_page_id == UUID(PAGE_ID)
    assert notion.created == []


@pytest.mark.anyio
async def test_confirm_accepts_official_app_notion_page_url(db_session: AsyncSession) -> None:
    item = await seed_candidate(db_session)
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    page_url = "https://app.notion.com/p/material"

    result = await RssInboxService(
        factory,
        RecordingNotion(page_url=page_url),
        INBOX_ID,
    ).push(item.id)

    assert result.notion_url == page_url


@pytest.mark.anyio
async def test_ignored_candidate_cannot_be_pushed(db_session: AsyncSession) -> None:
    item = await seed_candidate(db_session, status="ignored")
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    with pytest.raises(InboxPushError) as caught:
        await RssInboxService(factory, RecordingNotion(), INBOX_ID).push(item.id)

    assert caught.value.code == "RSS_CANDIDATE_NOT_PUSHABLE"
