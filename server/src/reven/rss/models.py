"""ORM models for RSS configuration and discovery."""

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from reven.db import Base
from reven.scheduling import utc_now


class RssSource(Base):
    __tablename__ = "rss_sources"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200))
    feed_url: Mapped[str] = mapped_column(Text, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class RssKeyword(Base):
    __tablename__ = "rss_keywords"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    term: Mapped[str] = mapped_column(String(200))
    normalized_term: Mapped[str] = mapped_column(String(200), unique=True)
    kind: Mapped[str] = mapped_column(String(16))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    embedding: Mapped[list[float] | None] = mapped_column(ARRAY(Float))
    embedding_model: Mapped[str | None] = mapped_column(String(100))
    embedding_dimension: Mapped[int | None] = mapped_column(Integer)
    embedding_term_hash: Mapped[str | None] = mapped_column(String(64))
    embedding_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    embedding_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class RssDiscoveryRun(Base):
    __tablename__ = "rss_discovery_runs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_date: Mapped[date] = mapped_column(Date, unique=True)
    status: Mapped[str] = mapped_column(String(16), default="running")
    source_count: Mapped[int] = mapped_column(Integer, default=0)
    fetched_count: Mapped[int] = mapped_column(Integer, default=0)
    new_count: Mapped[int] = mapped_column(Integer, default=0)
    candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list[dict[str, object]]] = mapped_column(JSONB, default=list)
    notification_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notification_error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RssItem(Base):
    __tablename__ = "rss_items"
    __table_args__ = (
        Index("uq_rss_items_url_key", "url_key", unique=True, postgresql_where="url_key IS NOT NULL"),
        Index("uq_rss_items_guid_key", "guid_key", unique=True, postgresql_where="guid_key IS NOT NULL"),
        Index("uq_rss_items_title_key", "title_key", unique=True),
        Index("ix_rss_items_candidate_scan", "status", "published_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_id: Mapped[UUID | None] = mapped_column(ForeignKey("rss_sources.id", ondelete="SET NULL"))
    first_seen_run_id: Mapped[UUID] = mapped_column(ForeignKey("rss_discovery_runs.id", ondelete="RESTRICT"))
    source_name: Mapped[str] = mapped_column(String(200))
    guid: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    url_key: Mapped[str | None] = mapped_column(String(64))
    guid_key: Mapped[str | None] = mapped_column(String(64))
    title_key: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text, default="")
    title_zh: Mapped[str] = mapped_column(Text)
    summary_zh: Mapped[str] = mapped_column(Text, default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(24), default="pending")
    positive_literal_matches: Mapped[list[str]] = mapped_column(JSONB, default=list)
    negative_literal_matches: Mapped[list[str]] = mapped_column(JSONB, default=list)
    bm25_score: Mapped[float] = mapped_column(Float, default=0.0)
    positive_embedding_score: Mapped[float] = mapped_column(Float, default=0.0)
    negative_embedding_score: Mapped[float] = mapped_column(Float, default=0.0)
    embedding_model: Mapped[str | None] = mapped_column(String(100))
    embedding_status: Mapped[str] = mapped_column(String(24), default="pending")
    model_status: Mapped[str] = mapped_column(String(24), default="skipped")
    model_score: Mapped[float | None] = mapped_column(Float)
    reason: Mapped[str | None] = mapped_column(Text)
    rules_version: Mapped[str | None] = mapped_column(String(32))
    screening_error: Mapped[str | None] = mapped_column(Text)
    screened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_pushed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
