"""ORM model for articles synced from Notion."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text
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
    content_sync_status: Mapped[str] = mapped_column(String(32), index=True, default="未同步")
    content_sync_error: Mapped[str | None] = mapped_column(Text)
    current_snapshot_id: Mapped[UUID | None] = mapped_column(ForeignKey("content_snapshots.id", ondelete="SET NULL"))
    selected_cover_asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("brand_assets.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


# 注册 Article 的跨聚合快照外键目标，避免仅导入文章模型时元数据不完整。
# 注册 Article 的品牌封面外键目标（品牌素材表）。
from reven.brand import models as brand_models  # noqa: E402,F401
from reven.content_sync import models as content_sync_models  # noqa: E402,F401
