"""Persistence models for content sync runs and immutable snapshots."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from reven.content_sync.domain import SyncRunStatus, SyncStage
from reven.db import Base
from reven.scheduling import utc_now


class ContentSyncRun(Base):
    __tablename__ = "content_sync_runs"
    __table_args__ = (
        Index(
            "uq_one_active_content_sync_per_article",
            "article_id",
            unique=True,
            postgresql_where=text("status IN ('等待中', '同步中')"),
        ),
        Index("ix_content_sync_runs_claim", "status", "next_attempt_at", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    article_id: Mapped[UUID] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32), default=SyncRunStatus.WAITING)
    stage: Mapped[str] = mapped_column(String(64), default=SyncStage.WAITING)
    source_last_edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    progress_current: Mapped[int] = mapped_column(Integer, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, default=0)
    current_media: Mapped[str | None] = mapped_column(Text)
    error_stage: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    error_media: Mapped[str | None] = mapped_column(Text)
    retryable: Mapped[bool] = mapped_column(Boolean, default=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    lease_token: Mapped[UUID | None] = mapped_column()
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class ContentSnapshot(Base):
    __tablename__ = "content_snapshots"
    __table_args__ = (
        UniqueConstraint("sync_run_id", name="uq_content_snapshot_sync_run"),
        UniqueConstraint(
            "article_id",
            "source_last_edited_at",
            "content_hash",
            name="uq_content_snapshot_article_version_hash",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    article_id: Mapped[UUID] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"), index=True)
    sync_run_id: Mapped[UUID] = mapped_column(ForeignKey("content_sync_runs.id", ondelete="RESTRICT"))
    source_last_edited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    title: Mapped[str] = mapped_column(Text)
    source_markdown: Mapped[str] = mapped_column(Text)
    portable_markdown: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    snapshot_metadata: Mapped[dict[str, object]] = mapped_column("metadata", JSONB, default=dict)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SnapshotAsset(Base):
    __tablename__ = "snapshot_assets"
    __table_args__ = (UniqueConstraint("snapshot_id", "ordinal", name="uq_snapshot_asset_ordinal"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    snapshot_id: Mapped[UUID] = mapped_column(ForeignKey("content_snapshots.id", ondelete="CASCADE"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(32))
    embedded: Mapped[bool] = mapped_column(Boolean, default=False)
    source_url: Mapped[str] = mapped_column(Text)
    storage_key: Mapped[str] = mapped_column(Text)
    public_url: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    mime_type: Mapped[str] = mapped_column(String(128))
    byte_size: Mapped[int] = mapped_column(BigInteger)
    filename: Mapped[str | None] = mapped_column(Text)
    alt_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
