"""Notion editorial index synchronization without fetching article bodies."""

from dataclasses import dataclass
from time import monotonic
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.articles.models import Article
from reven.articles.repository import ArticleRepository
from reven.domain import AutomationStatus, JobStatus, TargetChannel, parse_target_channels
from reven.integrations.notion.mapper import map_notion_page
from reven.integrations.notion.models import NotionSchemaError
from reven.jobs.models import PublicationJob
from reven.jobs.repository import JobRepository, compute_target_channels_hash
from reven.scheduling import database_now, utc_now
from reven.system.models import SystemState

_ACTIVE_STATUSES = (JobStatus.WAITING, JobStatus.PROCESSING, JobStatus.BLOCKED, JobStatus.FAILED)
MAX_SYNC_PAGES = 1000
NOTION_PAGE_SIZE = 100


class NotionPageClient(Protocol):
    async def query_data_source(
        self,
        data_source_id: str,
        *,
        start_cursor: str | None = None,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class SyncResult:
    created: int
    updated: int
    failed: int
    duration_ms: int


class NotionSyncService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        client: NotionPageClient,
        data_source_id: str,
    ) -> None:
        self.session_factory = session_factory
        self.client = client
        self.data_source_id = data_source_id

    async def sync_once(self) -> SyncResult:
        started = monotonic()
        cursor: str | None = None
        seen_cursors: set[str] = set()
        page_count = 0
        created = updated = failed = 0
        while True:
            response = await self.client.query_data_source(self.data_source_id, start_cursor=cursor)
            page_count += 1
            _validate_pagination(response, cursor, seen_cursors, page_count)
            for raw_page in _page_results(response):
                outcome = await self._sync_raw_page(raw_page)
                created += outcome == "created"
                updated += outcome == "updated"
                failed += outcome == "failed"
            cursor = _next_cursor(response)
            await self._save_state(cursor=cursor, completed=not response.get("has_more", False))
            if not response.get("has_more", False):
                break
        return SyncResult(created, updated, failed, round((monotonic() - started) * 1000))

    async def sync_page(self, page_id: UUID) -> SyncResult:
        started = monotonic()
        async with self.session_factory() as session:
            article = await ArticleRepository(session).get_by_id(page_id)
        if article is None:
            return SyncResult(0, 0, 1, round((monotonic() - started) * 1000))
        return await self._sync_known_page(article.notion_page_id, started)

    async def _sync_known_page(self, notion_page_id: str, started: float) -> SyncResult:
        cursor: str | None = None
        seen_cursors: set[str] = set()
        page_count = 0
        while True:
            response = await self.client.query_data_source(self.data_source_id, start_cursor=cursor)
            page_count += 1
            _validate_pagination(response, cursor, seen_cursors, page_count)
            for raw_page in _page_results(response):
                if raw_page.get("id") == notion_page_id:
                    outcome = await self._sync_raw_page(raw_page)
                    return SyncResult(
                        outcome == "created",
                        outcome == "updated",
                        outcome == "failed",
                        round((monotonic() - started) * 1000),
                    )
            if not response.get("has_more", False):
                return SyncResult(0, 0, 1, round((monotonic() - started) * 1000))
            cursor = _next_cursor(response)

    async def _sync_raw_page(self, raw_page: dict[str, Any]) -> str:
        try:
            mapped = map_notion_page(raw_page)
            async with self.session_factory.begin() as session:
                await _lock_notion_page(session, mapped.page_id)
                articles = ArticleRepository(session)
                existing = await articles.get_by_notion_page_id(mapped.page_id, for_update=True)
                article = await articles.upsert_from_notion(mapped)
                await _reconcile_job(session, article)
            return "created" if existing is None else "updated"
        except NotionSchemaError as exc:
            page_id = str(raw_page.get("id", "unknown"))
            await self._record_page_error(page_id, str(exc))
            return "failed"
        except ValueError as exc:
            page_id = str(raw_page.get("id", "unknown"))
            await self._record_page_error(page_id, f"页面处理失败（{type(exc).__name__}）")
            return "failed"

    async def _save_state(self, *, cursor: str | None, completed: bool) -> None:
        async with self.session_factory.begin() as session:
            await _lock_sync_state(session)
            state = await session.get(SystemState, "notion_sync")
            if state is None:
                state = SystemState(key="notion_sync")
                session.add(state)
            value = dict(state.value or {})
            value["cursor"] = cursor or ""
            if completed:
                value["last_success_at"] = utc_now().isoformat()
            state.value = value

    async def _record_page_error(self, page_id: str, error: str) -> None:
        async with self.session_factory.begin() as session:
            key = f"notion_sync_error:{page_id}"[:128]
            await _lock_transaction_key(session, f"reven:system_state:{key}")
            state = await session.get(SystemState, key)
            if state is None:
                state = SystemState(key=key)
                session.add(state)
            state.value = {"error": error, "recorded_at": utc_now().isoformat()}


async def _reconcile_job(session: AsyncSession, article: Article) -> None:
    job = await _active_job(session, article.id)
    if article.notion_status != "待发布":
        if job is not None and job.overall_status in (JobStatus.WAITING, JobStatus.BLOCKED):
            job.overall_status = JobStatus.CANCELLED
            article.automation_status = AutomationStatus.NOT_STARTED
        return
    if job is None:
        channels = _scheduled_channels(article.target_channels)
        await JobRepository(session).create_waiting(
            article_id=article.id,
            content_hash=None,
            target_channels=channels,
            scheduled_at=article.planned_at or await database_now(session),
            used_default=article.notion_metadata.get("target_channels_used_default") is True,
        )
        article.automation_status = AutomationStatus.WAITING
        return
    if job.overall_status == JobStatus.WAITING and job.content_hash is None:
        _update_waiting_job(job, article)
    elif job.overall_status == JobStatus.BLOCKED:
        article.automation_status = AutomationStatus.BLOCKED


async def _active_job(session: AsyncSession, article_id: UUID) -> PublicationJob | None:
    statement = (
        select(PublicationJob)
        .where(
            PublicationJob.article_id == article_id,
            PublicationJob.overall_status.in_(_ACTIVE_STATUSES),
        )
        .order_by(PublicationJob.created_at.desc())
        .with_for_update()
        .limit(1)
    )
    job: PublicationJob | None = await session.scalar(statement)
    return job


def _update_waiting_job(job: PublicationJob, article: Article) -> None:
    channels = _scheduled_channels(article.target_channels)
    job.target_channels = channels
    job.target_channels_hash = compute_target_channels_hash(channels)
    job.snapshot_metadata = {
        **job.snapshot_metadata,
        "target_channels_used_default": article.notion_metadata.get("target_channels_used_default") is True,
    }
    if article.planned_at is not None:
        job.scheduled_at = article.planned_at
    article.automation_status = AutomationStatus.WAITING


def _scheduled_channels(raw_channels: list[str]) -> list[str]:
    selection = parse_target_channels(raw_channels)
    return [channel.value for channel in TargetChannel if channel in selection.channels]


def _page_results(response: dict[str, Any]) -> list[dict[str, Any]]:
    results = response.get("results")
    if not isinstance(results, list):
        raise NotionSchemaError("Notion 查询响应缺少 results 列表")
    if not all(isinstance(item, dict) for item in results):
        raise NotionSchemaError("Notion 查询响应 results 包含非对象项")
    if len(results) > NOTION_PAGE_SIZE:
        raise NotionSchemaError("Notion 查询响应超过单页数量限制")
    return results


def _next_cursor(response: dict[str, Any]) -> str | None:
    cursor = response.get("next_cursor")
    if response.get("has_more") and not isinstance(cursor, str):
        raise NotionSchemaError("Notion 查询响应分页游标缺失")
    return cursor if isinstance(cursor, str) else None


def _validate_pagination(
    response: dict[str, Any],
    current: str | None,
    seen: set[str],
    page_count: int,
) -> None:
    if page_count > MAX_SYNC_PAGES:
        raise NotionSchemaError("Notion 同步分页超过安全上限")
    if current is not None:
        seen.add(current)
    next_cursor = _next_cursor(response)
    if next_cursor is not None and next_cursor in seen:
        raise NotionSchemaError("Notion 同步分页游标发生循环")


async def _lock_notion_page(session: AsyncSession, page_id: str) -> None:
    await _lock_transaction_key(session, f"reven:notion_page:{page_id}")


async def _lock_sync_state(session: AsyncSession) -> None:
    await _lock_transaction_key(session, "reven:notion_sync_state")


async def _lock_transaction_key(session: AsyncSession, key: str) -> None:
    statement = text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))")
    await session.execute(statement, {"key": key})
