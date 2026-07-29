"""独立于发布状态机的准备阶段通知 Outbox。"""

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from reven.articles.models import Article
from reven.db import Base
from reven.jobs.models import PublicationJob
from reven.publishing.notifications import DeliveryNotifier, Notification

logger = logging.getLogger(__name__)


class PreparationNotificationOutbox(Base):
    __tablename__ = "preparation_notification_outbox"
    __table_args__ = (Index("ix_preparation_notification_due", "status", "next_attempt_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    job_id: Mapped[UUID] = mapped_column(ForeignKey("publication_jobs.id"))
    article_id: Mapped[UUID] = mapped_column(ForeignKey("articles.id"))
    event: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict[str, object]] = mapped_column(JSONB)
    revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[UUID | None] = mapped_column()
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


def enqueue_preparation_notification(
    session: AsyncSession,
    job: PublicationJob,
    article: Article,
    *,
    event: str,
    stage: str,
    summary: str,
) -> None:
    marker = f"{event}:{article.notion_last_edited_at.isoformat()}:{summary}"
    if job.notification_state.get("_preparation_terminal_marker") == marker:
        return
    revision = _next_revision(job)
    fingerprint = hashlib.sha256(f"{job.id}:{event}:r{revision}".encode()).hexdigest()
    session.add(
        PreparationNotificationOutbox(
            fingerprint=fingerprint,
            job_id=job.id,
            article_id=article.id,
            event=event,
            revision=revision,
            payload={
                "title": article.title,
                "stage": stage,
                "summary": summary[:1000],
                "links": {"Notion": article.notion_url},
            },
            next_attempt_at=func.clock_timestamp(),
        )
    )
    job.notification_state = {**job.notification_state, "_preparation_terminal_marker": marker}


def _next_revision(job: PublicationJob) -> int:
    current = job.notification_state.get("_revision", 0)
    revision = (current if isinstance(current, int) else 0) + 1
    job.notification_state = {**job.notification_state, "_revision": revision}
    return revision


@dataclass(frozen=True)
class OutboxClaim:
    id: UUID
    lease_token: UUID
    notification: Notification


class PreparationNotificationTick:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        notifier: DeliveryNotifier,
        *,
        lease_seconds: int = 30,
        max_backoff_seconds: int = 3600,
    ) -> None:
        self.factory = factory
        self.notifier = notifier
        self.lease_seconds = lease_seconds
        self.max_backoff_seconds = max_backoff_seconds

    async def __call__(self) -> None:
        claim = await self._claim()
        if claim is None:
            return
        try:
            await self.notifier.send(claim.notification)
        except Exception as exc:
            logger.warning("准备阶段飞书通知失败（error_type=%s）", type(exc).__name__)
            await self._failed(claim, type(exc).__name__)
            return
        await self._sent(claim)

    async def _claim(self) -> OutboxClaim | None:
        async with self.factory.begin() as session:
            now = await _database_now(session)
            row = await session.scalar(
                select(PreparationNotificationOutbox)
                .where(
                    PreparationNotificationOutbox.status == "pending",
                    PreparationNotificationOutbox.next_attempt_at <= now,
                    (
                        PreparationNotificationOutbox.lease_expires_at.is_(None)
                        | (PreparationNotificationOutbox.lease_expires_at < now)
                    ),
                )
                .order_by(PreparationNotificationOutbox.next_attempt_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if row is None:
                return None
            token = uuid4()
            row.lease_token = token
            row.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
            return OutboxClaim(row.id, token, _notification(row.payload))

    async def _sent(self, claim: OutboxClaim) -> None:
        async with self.factory.begin() as session:
            now = await _database_now(session)
            await session.execute(
                update(PreparationNotificationOutbox)
                .where(
                    PreparationNotificationOutbox.id == claim.id,
                    PreparationNotificationOutbox.lease_token == claim.lease_token,
                    PreparationNotificationOutbox.lease_expires_at >= now,
                )
                .values(
                    status="sent",
                    attempts=PreparationNotificationOutbox.attempts + 1,
                    sent_at=now,
                    lease_token=None,
                    lease_expires_at=None,
                    last_error=None,
                )
            )

    async def _failed(self, claim: OutboxClaim, error_type: str) -> None:
        async with self.factory.begin() as session:
            now = await _database_now(session)
            row = await session.scalar(
                select(PreparationNotificationOutbox).where(
                    PreparationNotificationOutbox.id == claim.id,
                    PreparationNotificationOutbox.lease_token == claim.lease_token,
                    PreparationNotificationOutbox.lease_expires_at >= now,
                )
            )
            if row is None:
                return
            row.attempts += 1
            delay = min(2 ** min(row.attempts, 20), self.max_backoff_seconds)
            row.next_attempt_at = now + timedelta(seconds=delay)
            row.lease_token = None
            row.lease_expires_at = None
            row.last_error = error_type[:120]


async def _database_now(session: AsyncSession) -> datetime:
    now = await session.scalar(select(func.clock_timestamp()))
    if not isinstance(now, datetime):
        raise RuntimeError("数据库未返回有效时间")
    return now


def _notification(payload: dict[str, object]) -> Notification:
    links = payload.get("links")
    return Notification(
        str(payload.get("title", "")),
        str(payload.get("stage", "")),
        str(payload.get("summary", "")),
        {str(key): str(value) for key, value in links.items()} if isinstance(links, dict) else {},
    )
