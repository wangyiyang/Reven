"""Serial worker that turns a Notion version into one atomic snapshot."""

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.articles.models import Article
from reven.articles.repository import refresh_from_notion
from reven.content_sync.domain import ContentSyncStatus, SyncRunStatus, SyncStage
from reven.content_sync.models import ContentSnapshot, SnapshotAsset
from reven.content_sync.repository import ContentSyncClaim, ContentSyncRepository
from reven.integrations.notion.models import MappedNotionPage, NotionFile
from reven.scheduling import database_now


@dataclass(frozen=True)
class SourceDocument:
    page: MappedNotionPage
    markdown: str


@dataclass(frozen=True)
class ArchivedMedia:
    ordinal: int
    kind: str
    embedded: bool
    source_url: str
    storage_key: str
    public_url: str
    sha256: str
    mime_type: str
    byte_size: int
    filename: str | None = None
    alt_text: str | None = None


@dataclass(frozen=True)
class ArchivedContent:
    canonical_markdown: str
    portable_markdown: str
    media: tuple[ArchivedMedia, ...]


class ContentSource(Protocol):
    async def load(self, page_id: str) -> SourceDocument: ...

    async def current_version(self, page_id: str) -> datetime: ...


class MediaArchive(Protocol):
    async def archive(
        self,
        run_id: UUID,
        markdown: str,
        cover: NotionFile | None,
        *,
        progress: Callable[[str, int, int, str | None], Awaitable[None]] | None = None,
    ) -> ArchivedContent: ...


class ContentSyncFailure(Exception):  # noqa: N818 - 领域契约使用 Failure 表达可重试分类
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        media: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.media = media


class ContentSyncWorker:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        source: ContentSource,
        media_archive: MediaArchive,
        *,
        lease_seconds: int = 600,
    ) -> None:
        self.factory = factory
        self.source = source
        self.media_archive = media_archive
        self.lease_seconds = lease_seconds

    async def run_once(self) -> bool:
        claim = await self._claim()
        if claim is None:
            return False
        try:
            await self._run_with_heartbeat(claim)
        except ContentSyncFailure as exc:
            await self._record_failure(claim, exc)
        except Exception:
            await self._record_failure(
                claim,
                ContentSyncFailure("SYNC_UNEXPECTED", "内容同步发生未知错误，请稍后重试", retryable=True),
            )
        return True

    async def _run_with_heartbeat(self, claim: ContentSyncClaim) -> None:
        execution = asyncio.create_task(self._execute(claim))
        heartbeat = asyncio.create_task(self._heartbeat(claim))
        tasks = (execution, heartbeat)
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            if execution in done:
                await execution
                if heartbeat in done:
                    await heartbeat
                return
            await heartbeat
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _heartbeat(self, claim: ContentSyncClaim) -> None:
        interval = min(30.0, self.lease_seconds / 3)
        while True:
            await asyncio.sleep(interval)
            async with self.factory.begin() as session:
                renewed = await ContentSyncRepository(session).renew(
                    claim,
                    lease_seconds=self.lease_seconds,
                )
            if not renewed:
                raise ContentSyncFailure("SYNC_LEASE_LOST", "同步任务租约已失效", retryable=True)

    async def _claim(self) -> ContentSyncClaim | None:
        async with self.factory.begin() as session:
            return await ContentSyncRepository(session).claim_next(lease_seconds=self.lease_seconds)

    async def _execute(self, claim: ContentSyncClaim) -> None:
        page_id = await self._page_id(claim)
        source = await self.source.load(page_id)
        # 封面缺失不阻塞同步：快照照常生成，封面缺失由发布校验（cover_missing）兜底。
        await self._progress(claim, SyncStage.DISCOVERING_MEDIA)
        archived = await self.media_archive.archive(
            claim.run_id,
            source.markdown,
            source.page.cover,
            progress=self._media_progress(claim),
        )
        await self._progress(
            claim,
            SyncStage.COMMITTING_SNAPSHOT,
            current=len(archived.media),
            total=len(archived.media),
        )
        latest_version = await self.source.current_version(page_id)
        if latest_version != source.page.last_edited_at:
            raise ContentSyncFailure("SOURCE_CHANGED", "Notion 内容在同步期间发生变化，请重新同步")
        await self._commit(claim, source, archived)

    async def _page_id(self, claim: ContentSyncClaim) -> str:
        async with self.factory() as session:
            article = await session.get(Article, claim.article_id)
            if article is None:
                raise ContentSyncFailure("ARTICLE_NOT_FOUND", "稿件不存在")
            return article.notion_page_id

    async def _progress(
        self,
        claim: ContentSyncClaim,
        stage: str,
        *,
        current: int = 0,
        total: int = 0,
        media: str | None = None,
    ) -> None:
        async with self.factory.begin() as session:
            updated = await ContentSyncRepository(session).progress(
                claim,
                stage=stage,
                current=current,
                total=total,
                media=media,
            )
            if not updated:
                raise ContentSyncFailure("SYNC_LEASE_LOST", "同步任务租约已失效", retryable=True)

    def _media_progress(self, claim: ContentSyncClaim) -> Callable[[str, int, int, str | None], Awaitable[None]]:
        async def update(stage: str, current: int, total: int, media: str | None) -> None:
            await self._progress(claim, stage, current=current, total=total, media=media)

        return update

    async def _commit(
        self,
        claim: ContentSyncClaim,
        source: SourceDocument,
        archived: ArchivedContent,
    ) -> None:
        async with self.factory.begin() as session:
            repository = ContentSyncRepository(session)
            run = await repository.owned_run(claim, for_update=True)
            article = await session.scalar(select(Article).where(Article.id == claim.article_id).with_for_update())
            if run is None or article is None:
                raise ContentSyncFailure("SYNC_LEASE_LOST", "同步任务租约已失效", retryable=True)
            if article.notion_last_edited_at > source.page.last_edited_at:
                raise ContentSyncFailure("SOURCE_CHANGED", "Notion 内容在同步期间发生变化，请重新同步")
            now = await database_now(session)
            snapshot = await _persist_or_reuse_snapshot(session, article.id, run.id, source, archived, now)
            refresh_from_notion(article, source.page)
            article.current_snapshot_id = snapshot.id
            article.content_sync_status = ContentSyncStatus.SYNCED
            article.content_sync_error = None
            _complete_run(run, source.page.last_edited_at, len(archived.media), now)

    async def _record_failure(self, claim: ContentSyncClaim, failure: ContentSyncFailure) -> None:
        async with self.factory.begin() as session:
            repository = ContentSyncRepository(session)
            run = await repository.owned_run(claim, for_update=True)
            article = await session.scalar(select(Article).where(Article.id == claim.article_id).with_for_update())
            if run is None or article is None:
                return
            now = await database_now(session)
            _set_run_error(run, failure)
            if failure.retryable and claim.attempt_count < 3:
                run.status = SyncRunStatus.WAITING
                run.stage = SyncStage.WAITING
                run.next_attempt_at = now + timedelta(seconds=(30, 120)[claim.attempt_count - 1])
                run.lease_token = None
                run.lease_expires_at = None
                article.content_sync_status = ContentSyncStatus.SYNCING
                return
            run.status = SyncRunStatus.FAILED
            run.stage = SyncStage.FAILED
            run.finished_at = now
            run.lease_token = None
            run.lease_expires_at = None
            article.content_sync_status = ContentSyncStatus.FAILED
            article.content_sync_error = failure.message[:1000]


def _new_snapshot(
    article_id: UUID,
    run_id: UUID,
    source: SourceDocument,
    archived: ArchivedContent,
    now: datetime,
) -> ContentSnapshot:
    page = source.page
    portable = f"# {page.title.strip()}\n\n{archived.portable_markdown.strip()}\n"
    metadata: dict[str, object] = {
        "summary": page.summary,
        "categories": sorted(page.categories),
        "media_count": len(archived.media),
        "character_count": len(archived.canonical_markdown),
    }
    return ContentSnapshot(
        article_id=article_id,
        sync_run_id=run_id,
        source_last_edited_at=page.last_edited_at,
        title=page.title.strip(),
        source_markdown=archived.canonical_markdown,
        portable_markdown=portable,
        content_hash=_content_hash(source, archived),
        snapshot_metadata=metadata,
        synced_at=now,
        created_at=now,
    )


async def _persist_or_reuse_snapshot(
    session: AsyncSession,
    article_id: UUID,
    run_id: UUID,
    source: SourceDocument,
    archived: ArchivedContent,
    now: datetime,
) -> ContentSnapshot:
    candidate = _new_snapshot(article_id, run_id, source, archived, now)
    existing = await session.scalar(
        select(ContentSnapshot).where(
            ContentSnapshot.article_id == article_id,
            ContentSnapshot.source_last_edited_at == candidate.source_last_edited_at,
            ContentSnapshot.content_hash == candidate.content_hash,
        )
    )
    if existing is not None:
        assets = tuple(
            (
                await session.scalars(
                    select(SnapshotAsset)
                    .where(SnapshotAsset.snapshot_id == existing.id)
                    .order_by(SnapshotAsset.ordinal)
                )
            ).all()
        )
        if not _same_snapshot(existing, assets, candidate, archived.media):
            raise ContentSyncFailure("SNAPSHOT_CONFLICT", "相同内容版本的历史快照不一致，禁止覆盖")
        return existing
    session.add(candidate)
    await session.flush()
    session.add_all(_snapshot_assets(candidate.id, archived.media, now))
    return candidate


def _same_snapshot(
    existing: ContentSnapshot,
    assets: tuple[SnapshotAsset, ...],
    candidate: ContentSnapshot,
    media: tuple[ArchivedMedia, ...],
) -> bool:
    content_matches = (
        existing.title == candidate.title
        and existing.source_markdown == candidate.source_markdown
        and existing.portable_markdown == candidate.portable_markdown
        and existing.snapshot_metadata == candidate.snapshot_metadata
    )
    return content_matches and tuple(_stored_asset_signature(item) for item in assets) == tuple(
        _archived_asset_signature(item) for item in media
    )


def _stored_asset_signature(asset: SnapshotAsset) -> tuple[object, ...]:
    return (
        asset.ordinal,
        asset.kind,
        asset.embedded,
        asset.source_url,
        asset.storage_key,
        asset.public_url,
        asset.sha256,
        asset.mime_type,
        asset.byte_size,
        asset.filename,
        asset.alt_text,
    )


def _archived_asset_signature(asset: ArchivedMedia) -> tuple[object, ...]:
    return (
        asset.ordinal,
        asset.kind,
        asset.embedded,
        asset.source_url,
        asset.storage_key,
        asset.public_url,
        asset.sha256,
        asset.mime_type,
        asset.byte_size,
        asset.filename,
        asset.alt_text,
    )


def _snapshot_assets(snapshot_id: UUID, media: tuple[ArchivedMedia, ...], now: datetime) -> list[SnapshotAsset]:
    return [
        SnapshotAsset(
            snapshot_id=snapshot_id,
            ordinal=item.ordinal,
            kind=item.kind,
            embedded=item.embedded,
            source_url=item.source_url,
            storage_key=item.storage_key,
            public_url=item.public_url,
            sha256=item.sha256,
            mime_type=item.mime_type,
            byte_size=item.byte_size,
            filename=item.filename,
            alt_text=item.alt_text,
            created_at=now,
        )
        for item in media
    ]


def _content_hash(source: SourceDocument, archived: ArchivedContent) -> str:
    page = source.page
    payload = {
        "title": page.title.strip(),
        "summary": page.summary.strip(),
        "categories": sorted(page.categories),
        "markdown": archived.canonical_markdown.replace("\r\n", "\n").strip(),
        "source_last_edited_at": page.last_edited_at.isoformat(),
        "media": [item.sha256 for item in archived.media],
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _complete_run(run, source_version: datetime, media_count: int, now: datetime) -> None:  # type: ignore[no-untyped-def]
    run.status = SyncRunStatus.SUCCEEDED
    run.stage = SyncStage.COMPLETED
    run.source_last_edited_at = source_version
    run.progress_current = media_count
    run.progress_total = media_count
    run.current_media = None
    run.finished_at = now
    run.lease_token = None
    run.lease_expires_at = None


def _set_run_error(run, failure: ContentSyncFailure) -> None:  # type: ignore[no-untyped-def]
    run.error_stage = run.stage
    run.error_code = failure.code
    run.error_message = failure.message[:1000]
    run.error_media = failure.media
    run.retryable = failure.retryable
