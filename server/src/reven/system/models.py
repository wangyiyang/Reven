"""ORM model for singleton system state rows."""

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from reven.db import Base
from reven.scheduling import utc_now


class SystemState(Base):
    __tablename__ = "system_state"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
