"""ORM model for external integration credentials and status."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from reven.db import Base
from reven.scheduling import utc_now


class Integration(Base):
    __tablename__ = "integrations"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(String(32), unique=True)
    public_config: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    encrypted_secret: Mapped[str | None] = mapped_column(Text)
    connection_status: Mapped[str] = mapped_column(String(32), default="未测试")
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    last_latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class FeishuResourceBinding(Base):
    """飞书资源绑定：resource_type/purpose 白名单 + config JSONB（bitable: app_token/table_id）。

    同一 purpose 同时只允许一个启用绑定——由部分唯一索引
    uq_feishu_resource_bindings_enabled_purpose (WHERE enabled = true) 保证。
    """

    __tablename__ = "feishu_resource_bindings"
    __table_args__ = (
        Index(
            "uq_feishu_resource_bindings_enabled_purpose",
            "purpose",
            unique=True,
            postgresql_where=text("enabled = true"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    integration_id: Mapped[UUID] = mapped_column(ForeignKey("integrations.id", ondelete="CASCADE"))
    resource_type: Mapped[str] = mapped_column(String(32))
    purpose: Mapped[str] = mapped_column(String(64))
    config: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
