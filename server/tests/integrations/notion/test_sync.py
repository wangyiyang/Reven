import asyncio
from typing import Any

import pytest
from reven.articles.models import Article
from reven.articles.repository import ArticleRepository
from reven.domain import JobStatus
from reven.integrations.notion.models import NotionSchemaError, NotionTransientError
from reven.integrations.notion.sync import NotionSyncService
from reven.jobs.models import PublicationJob
from reven.system.models import SystemState
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
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


class MutableChannelsNotionPages(FakeNotionPages):
    def __init__(self) -> None:
        super().__init__()
        self.channels = ["个人博客"]

    async def query_data_source(
        self,
        _data_source_id: str,
        *,
        start_cursor: str | None = None,
    ) -> dict[str, Any]:
        page = _raw_page("待发布", suffix="1")
        page["properties"]["目标渠道"]["multi_select"] = [{"name": value} for value in self.channels]
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


class InvalidPlannedDateNotionPages(FakeNotionPages):
    async def query_data_source(
        self,
        _data_source_id: str,
        *,
        start_cursor: str | None = None,
    ) -> dict[str, Any]:
        invalid = _raw_page("待发布", suffix="1")
        invalid["properties"]["计划发布日"]["date"] = {"start": "ntn_secret"}
        valid = _raw_page("待发布", suffix="2")
        return {"results": [invalid, valid], "has_more": False, "next_cursor": None}


class SinglePageNotionPages(FakeNotionPages):
    async def query_data_source(
        self,
        _data_source_id: str,
        *,
        start_cursor: str | None = None,
    ) -> dict[str, Any]:
        return {
            "results": [_raw_page("待发布", suffix="1")],
            "has_more": False,
            "next_cursor": None,
        }


class FailingSecondPageNotionPages(FakeNotionPages):
    async def query_data_source(
        self,
        _data_source_id: str,
        *,
        start_cursor: str | None = None,
    ) -> dict[str, Any]:
        if start_cursor is not None:
            raise NotionTransientError("upstream unavailable")
        return {
            "results": [_raw_page("待发布", suffix="1")],
            "has_more": True,
            "next_cursor": "page-2",
        }


class InvalidResultItemNotionPages(FakeNotionPages):
    async def query_data_source(
        self,
        _data_source_id: str,
        *,
        start_cursor: str | None = None,
    ) -> dict[str, Any]:
        return {"results": ["not-a-page"], "has_more": False, "next_cursor": None}


class SingleInvalidPageNotionPages(FakeNotionPages):
    async def query_data_source(
        self,
        _data_source_id: str,
        *,
        start_cursor: str | None = None,
    ) -> dict[str, Any]:
        invalid = _raw_page("待发布", suffix="1")
        invalid["properties"].pop("标题")
        return {"results": [invalid], "has_more": False, "next_cursor": None}


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
async def test_sync_retries_blocked_job_validation_only_once(
    sync_service: NotionSyncService,
    db_session: AsyncSession,
) -> None:
    await sync_service.sync_once()
    job = await db_session.scalar(select(PublicationJob).order_by(PublicationJob.created_at).limit(1))
    assert job is not None
    job.overall_status = JobStatus.BLOCKED
    job.notification_state = {"fingerprint": "missing-cover"}
    job.blog_status = "失败"
    job.blog_error = "missing cover"
    job.blog_result = {"delivery_failure": {"status": JobStatus.BLOCKED}}
    await db_session.commit()

    await sync_service.sync_once()
    await db_session.refresh(job)

    assert job.overall_status == JobStatus.WAITING
    assert job.notification_state["fingerprint"] == "missing-cover"
    assert job.notification_state["_revision"] == 1
    assert job.blog_status == "待处理"
    assert "delivery_failure" not in job.blog_result

    job.overall_status = JobStatus.BLOCKED
    await db_session.commit()
    await sync_service.sync_once()
    await db_session.refresh(job)

    assert job.overall_status == JobStatus.BLOCKED
    assert job.notification_state["fingerprint"] == "missing-cover"


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
    assert job.snapshot_metadata["target_channels_used_default"] is True


@pytest.mark.anyio
async def test_sync_does_not_modify_frozen_waiting_job(db_session: AsyncSession) -> None:
    notion = MutableChannelsNotionPages()
    factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    service = NotionSyncService(factory, notion, "data-source")
    await service.sync_once()
    job = await db_session.scalar(select(PublicationJob).limit(1))
    assert job is not None
    job.content_hash = "a" * 64
    job.snapshot_metadata = {"notion_write_pending": True}
    original_hash = job.target_channels_hash
    await db_session.commit()
    notion.channels = ["微信公众号"]

    await service.sync_once()
    await db_session.refresh(job)

    assert job.target_channels == ["个人博客"]
    assert job.target_channels_hash == original_hash


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


@pytest.mark.anyio
async def test_sync_isolates_page_processing_error_and_redacts_details(
    db_session: AsyncSession,
) -> None:
    factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    service = NotionSyncService(factory, InvalidPlannedDateNotionPages(), "data-source")

    result = await service.sync_once()

    assert result.created == 1
    assert result.failed == 1
    error = await db_session.get(SystemState, "notion_sync_error:11111111-1111-1111-1111-111111111111")
    assert error is not None
    assert "ValueError" in str(error.value["error"])
    assert "ntn_secret" not in str(error.value)


@pytest.mark.anyio
async def test_sync_propagates_database_error_without_marking_success(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> None:
    factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    notion_pages = FakeNotionPages()
    service = NotionSyncService(factory, notion_pages, "data-source")
    original_upsert = ArticleRepository.upsert_from_notion
    attempts = 0

    async def fail_upsert(
        repository: ArticleRepository,
        page: Any,
    ) -> Article:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OperationalError("INSERT", {}, ConnectionError("database unavailable"))
        return await original_upsert(repository, page)

    monkeypatch.setattr(ArticleRepository, "upsert_from_notion", fail_upsert)

    with pytest.raises(OperationalError):
        await service.sync_once()

    assert await _count(db_session, Article) == 0
    assert notion_pages.cursors == [None]
    state = await db_session.get(SystemState, "notion_sync")
    assert state is None or "last_success_at" not in state.value


@pytest.mark.anyio
async def test_concurrent_syncs_create_one_article_and_one_active_job(
    db_session: AsyncSession,
) -> None:
    factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    first = NotionSyncService(factory, SinglePageNotionPages(), "data-source")
    second = NotionSyncService(factory, SinglePageNotionPages(), "data-source")

    results = await asyncio.gather(first.sync_once(), second.sync_once())

    assert sum(result.created for result in results) == 1
    assert sum(result.updated for result in results) == 1
    assert await _count(db_session, Article) == 1
    assert (
        await _count(
            db_session,
            PublicationJob,
            PublicationJob.overall_status.in_([JobStatus.WAITING, JobStatus.PROCESSING, JobStatus.BLOCKED]),
        )
        == 1
    )


@pytest.mark.anyio
async def test_incomplete_sync_preserves_previous_success_time(
    db_session: AsyncSession,
) -> None:
    old_success = "2026-07-01T00:00:00+00:00"
    db_session.add(
        SystemState(
            key="notion_sync",
            value={"cursor": "", "last_success_at": old_success},
        )
    )
    await db_session.commit()
    factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    service = NotionSyncService(factory, FailingSecondPageNotionPages(), "data-source")

    with pytest.raises(NotionTransientError):
        await service.sync_once()

    state = await db_session.get(SystemState, "notion_sync")
    assert state is not None
    await db_session.refresh(state)
    assert state.value == {"cursor": "page-2", "last_success_at": old_success}


@pytest.mark.anyio
async def test_sync_rejects_non_object_result_items(
    db_session: AsyncSession,
) -> None:
    factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    service = NotionSyncService(factory, InvalidResultItemNotionPages(), "data-source")

    with pytest.raises(NotionSchemaError):
        await service.sync_once()

    assert await db_session.get(SystemState, "notion_sync") is None


@pytest.mark.anyio
async def test_concurrent_invalid_page_syncs_share_one_error_state(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> None:
    factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    first = NotionSyncService(factory, SingleInvalidPageNotionPages(), "data-source")
    second = NotionSyncService(factory, SingleInvalidPageNotionPages(), "data-source")
    original_record_error = NotionSyncService._record_page_error
    both_ready = asyncio.Event()
    ready_count = 0

    async def synchronize_error_writes(
        service: NotionSyncService,
        page_id: str,
        error: str,
    ) -> None:
        nonlocal ready_count
        ready_count += 1
        if ready_count == 2:
            both_ready.set()
        await both_ready.wait()
        await original_record_error(service, page_id, error)

    monkeypatch.setattr(
        NotionSyncService,
        "_record_page_error",
        synchronize_error_writes,
    )

    results = await asyncio.gather(first.sync_once(), second.sync_once())

    assert [result.failed for result in results] == [1, 1]
    errors = await db_session.scalars(select(SystemState).where(SystemState.key.like("notion_sync_error:%")))
    assert len(list(errors)) == 1
