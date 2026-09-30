"""通知投递记录：业务键 + 自然日唯一去重，支撑定时推送幂等防骚扰。"""

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import Date, DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from reven.db import Base
from reven.scheduling import utc_now


class NotificationLog(Base):
    __tablename__ = "notification_logs"
    __table_args__ = (UniqueConstraint("biz_key", "notified_on", name="uq_notification_logs_biz_key_on"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    biz_key: Mapped[str] = mapped_column(String(200))
    notified_on: Mapped[date] = mapped_column(Date)
    # 投递通道（chat=定向会话 / whitelist=机器人白名单接收人）；认领占位时为 pending
    channel: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
