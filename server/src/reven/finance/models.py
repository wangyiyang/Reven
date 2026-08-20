"""ORM model for one-person company finance entries."""

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import Date, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from reven.db import Base
from reven.scheduling import utc_now


class FinanceEntry(Base):
    __tablename__ = "finance_entries"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    kind: Mapped[str] = mapped_column(String(16), index=True)
    name: Mapped[str] = mapped_column(String(200))
    amount_cents: Mapped[int] = mapped_column(Integer)
    category: Mapped[str | None] = mapped_column(String(100), index=True)
    occurred_on: Mapped[date] = mapped_column(Date, index=True)
    due_on: Mapped[date | None] = mapped_column(Date)
    recurrence: Mapped[str | None] = mapped_column(String(32))
    source: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(32), default="已记录", index=True)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
