"""ORM model for publication jobs with two-stage (plan/execute) lifecycle."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from reven.db import Base
from reven.scheduling import utc_now


class PublicationJob(Base):
    __tablename__ = "publication_jobs"
    __table_args__ = (
        UniqueConstraint(
            "article_id",
            "content_hash",
            "target_channels_hash",
            name="uq_job_article_version_channels",
        ),
        Index(
            "uq_one_unfrozen_job_per_article",
            "article_id",
            unique=True,
            postgresql_where=text("content_hash IS NULL AND overall_status IN ('等待中', '处理中', '阻塞')"),
        ),
        Index("ix_publication_jobs_due_scan", "overall_status", "scheduled_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    article_id: Mapped[UUID] = mapped_column(ForeignKey("articles.id"))
    snapshot_id: Mapped[UUID | None] = mapped_column(ForeignKey("content_snapshots.id", ondelete="RESTRICT"))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    target_channels: Mapped[list[str]] = mapped_column(JSONB)
    target_channels_hash: Mapped[str] = mapped_column(String(64))
    source_markdown: Mapped[str | None] = mapped_column(Text)
    snapshot_metadata: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    wechat_html: Mapped[str | None] = mapped_column(Text)
    overall_status: Mapped[str] = mapped_column(String(32), index=True)
    blog_status: Mapped[str] = mapped_column(String(32))
    wechat_status: Mapped[str] = mapped_column(String(32))
    blog_result: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    wechat_result: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    notification_state: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    attempt_count: Mapped[int] = mapped_column(default=0)
    blog_attempt_count: Mapped[int] = mapped_column(default=0)
    wechat_attempt_count: Mapped[int] = mapped_column(default=0)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[UUID | None] = mapped_column(nullable=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    blog_error: Mapped[str | None] = mapped_column(Text)
    wechat_error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
