"""ORM models and value enums for the talents domain."""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import Date, DateTime, ForeignKey, Index, Numeric, SmallInteger, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from reven.db import Base
from reven.scheduling import utc_now


class TalentStatus(StrEnum):
    CANDIDATE = "候选"
    CONTACTING = "接洽中"
    COOPERATED = "已合作"
    SHELVED = "搁置"


class InteractionChannel(StrEnum):
    IN_PERSON = "面谈"
    CALL = "电话语音"
    WECHAT = "微信"
    EMAIL = "邮件"


class RateUnit(StrEnum):
    HOURLY = "按小时"
    DAILY = "按天"
    PER_PROJECT = "按项目"


class Talent(Base):
    __tablename__ = "talents"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(Text)
    organization: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    wechat: Mapped[str | None] = mapped_column(String(100), nullable=True)
    preferences: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    capability: Mapped[str | None] = mapped_column(Text, nullable=True)
    engagement_terms: Mapped[str | None] = mapped_column(Text, nullable=True)
    availability: Mapped[str | None] = mapped_column(Text, nullable=True)
    rate_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    rate_unit: Mapped[str | None] = mapped_column(String(16), nullable=True)
    rating: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=TalentStatus.CANDIDATE, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class TalentInteraction(Base):
    __tablename__ = "talent_interactions"
    __table_args__ = (
        Index("ix_talent_interactions_talent_id_occurred_on", "talent_id", "occurred_on"),
        Index("ix_talent_interactions_next_due_on", "next_due_on"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    talent_id: Mapped[UUID] = mapped_column(ForeignKey("talents.id", ondelete="CASCADE"))
    occurred_on: Mapped[date] = mapped_column(Date)
    channel: Mapped[str] = mapped_column(String(16))
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_due_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class TalentExperience(Base):
    __tablename__ = "talent_experiences"
    __table_args__ = (Index("ix_talent_experiences_talent_id_start_on", "talent_id", "start_on"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    talent_id: Mapped[UUID] = mapped_column(ForeignKey("talents.id", ondelete="CASCADE"))
    company: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_on: Mapped[date] = mapped_column(Date)
    end_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class TalentEducation(Base):
    __tablename__ = "talent_educations"
    __table_args__ = (Index("ix_talent_educations_talent_id_start_on", "talent_id", "start_on"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    talent_id: Mapped[UUID] = mapped_column(ForeignKey("talents.id", ondelete="CASCADE"))
    school: Mapped[str] = mapped_column(Text)
    degree: Mapped[str | None] = mapped_column(Text, nullable=True)
    major: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_on: Mapped[date] = mapped_column(Date)
    end_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
