from typing import Any

import pytest
from reven.articles.models import Article
from reven.domain import JobStatus
from reven.integrations.notion.sync import NotionSyncService
from reven.jobs.models import PublicationJob
from reven.system.models import SystemState
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class FakeNotionPages:
    def __init__(self) -> None:
        self.status = "待发布"
        self.cursors: list[str | None] = []

    def set_status(self, status: str) -> None:
        self.status = status

    async def query_data_source(
        self,
        _data_source_id: str,
        *,
        start_cursor: str | None = None,
    ) -> dict[str, Any]:
        self.cursors.append(start_cursor)
        page = _raw_page(self.status, suffix="1" if start_cursor is None else "2")
        return {
            "results": [page],
            "has_more": start_cursor is None,
            "next_cursor": "page-2" if start_cursor is None else None,
        }


class EmptyChannelsNotionPages(FakeNotionPages):
    async def query_data_source(
        self,
        _data_source_id: str,
        *,
        start_cursor: str | None = None,
    ) -> dict[str, Any]:
        page = _raw_page("待发布", suffix="1")
        page["properties"]["目标渠道"]["multi_select"] = []
        return {"results": [page], "has_more": False, "next_cursor": None}


class PartiallyInvalidNotionPages(FakeNotionPages):
    async def query_data_source(
        self,
        _data_source_id: str,
        *,
        start_cursor: str | None = None,
    ) -> dict[str, Any]:
        invalid = _raw_page("待发布", suffix="1")
        invalid["properties"].pop("标题")
        valid = _raw_page("待发布", suffix="2")
        return {"results": [invalid, valid], "has_more": False, "next_cursor": None}


def _raw_page(status: str, *, suffix: str) -> dict[str, Any]:
    page_id = f"11111111-1111-1111-1111-11111111111{suffix}"
    return {
        "id": page_id,
        "url": f"https://www.notion.so/{page_id}",
        "last_edited_time": "2026-07-29T08:00:00+00:00",
        "properties": {
            "标题": {"type": "title", "title": [{"plain_text": f"稿件 {suffix}"}]},
            "状态": {"type": "status", "status": {"name": status}},
            "目标渠道": {
                "type": "multi_select",
                "multi_select": [{"name": "个人博客"}],
            },
            "计划发布日": {"type": "date", "date": None},
        },
    }


@pytest.fixture
def notion_pages() -> FakeNotionPages:
    return FakeNotionPages()


@pytest.fixture
def sync_service(
    db_session: AsyncSession,
    notion_pages: FakeNotionPages,
) -> NotionSyncService:
    factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    return NotionSyncService(factory, notion_pages, "data-source")


async def _count(session: AsyncSession, model: type[Article] | type[PublicationJob], *criteria: Any) -> int:
    statement = select(func.count()).select_from(model)
    if criteria:
        statement = statement.where(*criteria)
    return int(await session.scalar(statement) or 0)


@pytest.mark.anyio
async def test_sync_upserts_articles_and_cancels_waiting_job_when_status_changes(
    sync_service: NotionSyncService,
    notion_pages: FakeNotionPages,
    db_session: AsyncSession,
) -> None:
    notion_pages.set_status("待发布")
    await sync_service.sync_once()
    assert await _count(db_session, Article) == 2
    assert await _count(db_session, PublicationJob, PublicationJob.overall_status == JobStatus.WAITING) == 2

    notion_pages.set_status("撰写中")
    await sync_service.sync_once()

    article = await db_session.scalar(select(Article).order_by(Article.notion_page_id).limit(1))
    assert article is not None
    assert article.notion_status == "撰写中"
    assert await _count(db_session, PublicationJob, PublicationJob.overall_status == JobStatus.CANCELLED) == 2


@pytest.mark.anyio
async def test_sync_traverses_all_pages_and_persists_success_state(
    sync_service: NotionSyncService,
    notion_pages: FakeNotionPages,
    db_session: AsyncSession,
) -> None:
    result = await sync_service.sync_once()

    assert notion_pages.cursors == [None, "page-2"]
    assert result.created == 2
    assert result.updated == 0
    assert result.failed == 0
    assert result.duration_ms >= 0
    state = await db_session.get(SystemState, "notion_sync")
    assert state is not None
    assert state.value["cursor"] == ""
    assert "last_success_at" in state.value


@pytest.mark.anyio
async def test_sync_does_not_move_unscheduled_waiting_job_forward(
    sync_service: NotionSyncService,
    db_session: AsyncSession,
) -> None:
    await sync_service.sync_once()
    first_job = await db_session.scalar(select(PublicationJob).order_by(PublicationJob.created_at).limit(1))
    assert first_job is not None
    scheduled_at = first_job.scheduled_at

    await sync_service.sync_once()
    await db_session.refresh(first_job)

    assert first_job.scheduled_at == scheduled_at


@pytest.mark.anyio
async def test_sync_does_not_modify_processing_job(
    sync_service: NotionSyncService,
    notion_pages: FakeNotionPages,
    db_session: AsyncSession,
) -> None:
    await sync_service.sync_once()
    job = await db_session.scalar(select(PublicationJob).order_by(PublicationJob.created_at).limit(1))
    assert job is not None
    job.overall_status = JobStatus.PROCESSING
    original_channels = list(job.target_channels)
    await db_session.commit()
    notion_pages.set_status("撰写中")

    await sync_service.sync_once()
    await db_session.refresh(job)

    assert job.overall_status == JobStatus.PROCESSING
    assert job.target_channels == original_channels


@pytest.mark.anyio
async def test_sync_returns_blocked_job_to_waiting_validation(
    sync_service: NotionSyncService,
    db_session: AsyncSession,
) -> None:
    await sync_service.sync_once()
    job = await db_session.scalar(select(PublicationJob).order_by(PublicationJob.created_at).limit(1))
    assert job is not None
    job.overall_status = JobStatus.BLOCKED
    job.notification_state = {"fingerprint": "missing-cover"}
    await db_session.commit()

    await sync_service.sync_once()
    await db_session.refresh(job)

    assert job.overall_status == JobStatus.WAITING
    assert job.notification_state == {"fingerprint": "missing-cover"}


@pytest.mark.anyio
async def test_sync_uses_default_channels_when_notion_selection_is_empty(
    db_session: AsyncSession,
) -> None:
    factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    service = NotionSyncService(factory, EmptyChannelsNotionPages(), "data-source")

    await service.sync_once()

    job = await db_session.scalar(select(PublicationJob).limit(1))
    assert job is not None
    assert set(job.target_channels) == {"个人博客", "微信公众号"}


@pytest.mark.anyio
async def test_sync_records_invalid_page_and_continues(
    db_session: AsyncSession,
) -> None:
    factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    service = NotionSyncService(factory, PartiallyInvalidNotionPages(), "data-source")

    result = await service.sync_once()

    assert result.created == 1
    assert result.failed == 1
    error = await db_session.get(SystemState, "notion_sync_error:11111111-1111-1111-1111-111111111111")
    assert error is not None
    assert "标题" in str(error.value["error"])
