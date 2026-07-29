"""ORM model for articles synced from Notion."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from reven.db import Base
from reven.scheduling import utc_now


class Article(Base):
    __tablename__ = "articles"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    notion_page_id: Mapped[str] = mapped_column(String(36), unique=True)
    notion_url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    notion_status: Mapped[str] = mapped_column(String(32), index=True)
    automation_status: Mapped[str] = mapped_column(String(32), index=True, default="未开始")
    target_channels: Mapped[list[str]] = mapped_column(JSONB, default=list)
    planned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cover_metadata: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    notion_metadata: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    notion_last_edited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
