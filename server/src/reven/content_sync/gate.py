"""Fail-closed access to the one current immutable content snapshot."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.articles.models import Article
from reven.content_sync.domain import ContentSyncStatus
from reven.content_sync.executor import ContentSyncFailure
from reven.content_sync.models import ContentSnapshot, SnapshotAsset


class SourceVersionReader(Protocol):
    async def current_version(self, page_id: str) -> datetime: ...


class AssetIntegrityVerifier(Protocol):
    async def verify(self, assets: tuple["SnapshotAssetView", ...]) -> None: ...


@dataclass(frozen=True)
class SnapshotAssetView:
    ordinal: int
    kind: str
    embedded: bool
    storage_key: str
    public_url: str
    sha256: str
    mime_type: str
    byte_size: int
    filename: str | None
    alt_text: str | None


@dataclass(frozen=True)
class CurrentSnapshotView:
    id: UUID
    article_id: UUID
    source_last_edited_at: datetime
    synced_at: datetime
    title: str
    source_markdown: str
    portable_markdown: str
    content_hash: str
    metadata: dict[str, object]
    assets: tuple[SnapshotAssetView, ...]


@dataclass(frozen=True)
class SnapshotUnavailableError(Exception):
    code: str
    message: str


class CurrentSnapshotGate:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        source: SourceVersionReader,
        assets: AssetIntegrityVerifier | None = None,
    ) -> None:
        self.factory = factory
        self.source = source
        self.asset_verifier = assets

    async def require(self, article_id: UUID) -> CurrentSnapshotView:
        loaded = await self._load(article_id)
        if loaded is None:
            raise SnapshotUnavailableError("SNAPSHOT_UNAVAILABLE", "稿件没有可输出的有效快照")
        article, snapshot, assets = loaded
        try:
            current_version = await self.source.current_version(article.notion_page_id)
        except Exception as exc:
            await self._invalidate(article.id, snapshot.id, ContentSyncStatus.FAILED, "无法确认 Notion 最新版本")
            code = exc.code if isinstance(exc, ContentSyncFailure) else "NOTION_UNAVAILABLE"
            raise SnapshotUnavailableError(code, "无法确认 Notion 最新版本，已禁止输出") from exc
        if current_version != snapshot.source_last_edited_at:
            await self._invalidate(article.id, snapshot.id, ContentSyncStatus.STALE, "Notion 内容已发生变化")
            raise SnapshotUnavailableError("SNAPSHOT_STALE", "Notion 内容已变化，请重新同步")
        current = _snapshot_view(snapshot, assets)
        if self.asset_verifier is not None:
            try:
                await self.asset_verifier.verify(current.assets)
            except Exception as exc:
                await self._invalidate(article.id, snapshot.id, ContentSyncStatus.FAILED, "对象存储资产无法确认")
                raise SnapshotUnavailableError(
                    "SNAPSHOT_ASSET_UNAVAILABLE",
                    "对象存储资产无法确认，已禁止输出",
                ) from exc
        return current

    async def _load(
        self,
        article_id: UUID,
    ) -> tuple[Article, ContentSnapshot, tuple[SnapshotAsset, ...]] | None:
        async with self.factory() as session:
            article = await session.get(Article, article_id)
            if (
                article is None
                or article.content_sync_status != ContentSyncStatus.SYNCED
                or article.current_snapshot_id is None
            ):
                return None
            snapshot = await session.get(ContentSnapshot, article.current_snapshot_id)
            if snapshot is None:
                return None
            assets = tuple(
                (
                    await session.scalars(
                        select(SnapshotAsset)
                        .where(SnapshotAsset.snapshot_id == snapshot.id)
                        .order_by(SnapshotAsset.ordinal)
                    )
                ).all()
            )
            return article, snapshot, assets

    async def _invalidate(
        self,
        article_id: UUID,
        snapshot_id: UUID,
        status: str,
        error: str,
    ) -> None:
        async with self.factory.begin() as session:
            article = await session.scalar(select(Article).where(Article.id == article_id).with_for_update())
            if article is None or article.current_snapshot_id != snapshot_id:
                return
            article.content_sync_status = status
            article.content_sync_error = error


def _snapshot_view(snapshot: ContentSnapshot, assets: tuple[SnapshotAsset, ...]) -> CurrentSnapshotView:
    return CurrentSnapshotView(
        id=snapshot.id,
        article_id=snapshot.article_id,
        source_last_edited_at=snapshot.source_last_edited_at,
        synced_at=snapshot.synced_at,
        title=snapshot.title,
        source_markdown=snapshot.source_markdown,
        portable_markdown=snapshot.portable_markdown,
        content_hash=snapshot.content_hash,
        metadata=snapshot.snapshot_metadata,
        assets=tuple(_asset_view(item) for item in assets),
    )


def _asset_view(asset: SnapshotAsset) -> SnapshotAssetView:
    return SnapshotAssetView(
        ordinal=asset.ordinal,
        kind=asset.kind,
        embedded=asset.embedded,
        storage_key=asset.storage_key,
        public_url=asset.public_url,
        sha256=asset.sha256,
        mime_type=asset.mime_type,
        byte_size=asset.byte_size,
        filename=asset.filename,
        alt_text=asset.alt_text,
    )
