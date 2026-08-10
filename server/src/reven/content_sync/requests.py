"""Transactional public interface for requesting and observing content sync."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.articles.models import Article
from reven.content_sync.domain import ContentSyncStatus, SyncRunStatus
from reven.content_sync.models import ContentSnapshot, ContentSyncRun
from reven.scheduling import database_now

_ACTIVE_STATUSES = (SyncRunStatus.WAITING, SyncRunStatus.PROCESSING)


@dataclass(frozen=True)
class SyncRunView:
    id: UUID
    article_id: UUID
    status: str
    stage: str
    progress_current: int
    progress_total: int
    current_media: str | None
    error_stage: str | None
    error_code: str | None
    error_message: str | None
    error_media: str | None
    retryable: bool
    attempt_count: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class SyncRequestResult:
    run: SyncRunView
    created: bool


@dataclass(frozen=True)
class ArticleSyncState:
    status: str
    current_snapshot_id: UUID | None
    latest_run_id: UUID | None
    outputs_enabled: bool
    error: str | None


@dataclass(frozen=True)
class ContentSyncRequestError(Exception):
    code: str
    message: str


class CurrentVersionSource(Protocol):
    async def current_version(self, page_id: str) -> datetime: ...


class ContentSyncRequestService:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        source: CurrentVersionSource | None = None,
    ) -> None:
        self.factory = factory
        self.source = source

    async def request(self, article_id: UUID) -> SyncRequestResult:
        confirmed_run_id = await self._confirmed_current(article_id)
        async with self.factory.begin() as session:
            article = await session.scalar(select(Article).where(Article.id == article_id).with_for_update())
            if article is None:
                raise ContentSyncRequestError("ARTICLE_NOT_FOUND", "稿件不存在")
            active = await _active_run(session, article_id)
            if active is not None:
                return SyncRequestResult(_run_view(active), created=False)
            if confirmed_run_id is not None:
                current = await _unchanged_current_run(session, article)
                if current is not None and current.id == confirmed_run_id:
                    return SyncRequestResult(_run_view(current), created=False)
            run = ContentSyncRun(
                article_id=article.id,
                next_attempt_at=await database_now(session),
            )
            session.add(run)
            article.content_sync_status = ContentSyncStatus.SYNCING
            article.content_sync_error = None
            await session.flush()
            return SyncRequestResult(_run_view(run), created=True)

    async def _confirmed_current(self, article_id: UUID) -> UUID | None:
        if self.source is None:
            return None
        async with self.factory() as session:
            article = await session.get(Article, article_id)
            if article is None:
                return None
            current = await _unchanged_current_run(session, article)
            page_id = article.notion_page_id
            version = article.notion_last_edited_at
        if current is None:
            return None
        try:
            live_version = await self.source.current_version(page_id)
        except Exception:
            return None
        return current.id if live_version == version else None

    async def get_run(self, article_id: UUID, run_id: UUID) -> SyncRunView | None:
        async with self.factory() as session:
            run = await session.scalar(
                select(ContentSyncRun).where(
                    ContentSyncRun.id == run_id,
                    ContentSyncRun.article_id == article_id,
                )
            )
            return _run_view(run) if run is not None else None

    async def get_article_state(self, article_id: UUID) -> ArticleSyncState | None:
        async with self.factory() as session:
            article = await session.get(Article, article_id)
            if article is None:
                return None
            latest_run_id = await session.scalar(
                select(ContentSyncRun.id)
                .where(ContentSyncRun.article_id == article_id)
                .order_by(desc(ContentSyncRun.created_at), desc(ContentSyncRun.id))
                .limit(1)
            )
            snapshot = (
                await session.get(ContentSnapshot, article.current_snapshot_id)
                if article.current_snapshot_id is not None
                else None
            )
            enabled = (
                article.content_sync_status == ContentSyncStatus.SYNCED
                and snapshot is not None
                and snapshot.source_last_edited_at == article.notion_last_edited_at
            )
            return ArticleSyncState(
                status=article.content_sync_status,
                current_snapshot_id=article.current_snapshot_id,
                latest_run_id=latest_run_id,
                outputs_enabled=enabled,
                error=article.content_sync_error,
            )


async def _active_run(session: AsyncSession, article_id: UUID) -> ContentSyncRun | None:
    run: ContentSyncRun | None = await session.scalar(
        select(ContentSyncRun)
        .where(ContentSyncRun.article_id == article_id, ContentSyncRun.status.in_(_ACTIVE_STATUSES))
        .order_by(desc(ContentSyncRun.created_at), desc(ContentSyncRun.id))
        .limit(1)
    )
    return run


async def _unchanged_current_run(session: AsyncSession, article: Article) -> ContentSyncRun | None:
    if article.content_sync_status != ContentSyncStatus.SYNCED or article.current_snapshot_id is None:
        return None
    snapshot = await session.get(ContentSnapshot, article.current_snapshot_id)
    if snapshot is None or snapshot.source_last_edited_at != article.notion_last_edited_at:
        return None
    return await session.get(ContentSyncRun, snapshot.sync_run_id)


def _run_view(run: ContentSyncRun) -> SyncRunView:
    return SyncRunView(
        id=run.id,
        article_id=run.article_id,
        status=run.status,
        stage=run.stage,
        progress_current=run.progress_current,
        progress_total=run.progress_total,
        current_media=run.current_media,
        error_stage=run.error_stage,
        error_code=run.error_code,
        error_message=run.error_message,
        error_media=run.error_media,
        retryable=run.retryable,
        attempt_count=run.attempt_count,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )
