"""品牌领域 ORM 模型：版本化品牌档案、渠道模板、品牌素材与迁移记录。"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Boolean, DateTime, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from reven.db import Base
from reven.scheduling import utc_now


class BrandVersion(Base):
    __tablename__ = "brand_versions"
    __table_args__ = (
        UniqueConstraint("version", name="uq_brand_versions_version"),
        Index(
            "uq_one_published_brand",
            "status",
            unique=True,
            postgresql_where=text("status = '已发布'"),
        ),
        Index(
            "uq_one_draft_brand",
            "status",
            unique=True,
            postgresql_where=text("status = '草稿'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    payload: Mapped[dict[str, object]] = mapped_column(JSONB)
    source: Mapped[str] = mapped_column(String(16), default="手动")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class ChannelTemplateVersion(Base):
    __tablename__ = "channel_template_versions"
    __table_args__ = (
        UniqueConstraint("channel", "version", name="uq_channel_template_version"),
        Index(
            "uq_one_published_channel_template",
            "channel",
            "status",
            unique=True,
            postgresql_where=text("status = '已发布'"),
        ),
        Index(
            "uq_one_draft_channel_template",
            "channel",
            "status",
            unique=True,
            postgresql_where=text("status = '草稿'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    channel: Mapped[str] = mapped_column(String(16))
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    payload: Mapped[dict[str, object]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BrandAsset(Base):
    __tablename__ = "brand_assets"
    __table_args__ = (Index("uq_brand_assets_sha256", "sha256", unique=True),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    purpose: Mapped[str] = mapped_column(String(32))
    label: Mapped[str] = mapped_column(String(200))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    storage_key: Mapped[str] = mapped_column(Text)
    public_url: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    mime_type: Mapped[str] = mapped_column(String(128))
    byte_size: Mapped[int] = mapped_column(BigInteger)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(16), default="上传")
    source_ref: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class BrandImportRun(Base):
    __tablename__ = "brand_import_runs"
    __table_args__ = (Index("ix_brand_import_runs_page", "notion_page_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    notion_page_id: Mapped[str] = mapped_column(String(64))
    dry_run: Mapped[bool] = mapped_column(Boolean)
    status: Mapped[str] = mapped_column(String(16))
    report: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
