"""独立于发布状态机的统一通知 Outbox。"""

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
from reven.scheduling import database_now

logger = logging.getLogger(__name__)


class NotificationOutbox(Base):
    __tablename__ = "notification_outbox"
    __table_args__ = (Index("ix_notification_outbox_due", "status", "next_attempt_at"),)

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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp())


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
    enqueue_notification(
        session,
        job,
        article,
        event=event,
        stage=stage,
        summary=summary,
        revision=revision,
    )
    job.notification_state = {**job.notification_state, "_preparation_terminal_marker": marker}


def enqueue_notification(
    session: AsyncSession,
    job: PublicationJob,
    article: Article,
    *,
    event: str,
    stage: str,
    summary: str,
    revision: int,
    error_code: str | None = None,
    channel: str | None = None,
    links: dict[str, str] | None = None,
) -> None:
    fingerprint = _fingerprint(job.id, event, revision, error_code, channel)
    session.add(
        NotificationOutbox(
            fingerprint=fingerprint,
            job_id=job.id,
            article_id=article.id,
            event=event,
            revision=revision,
            payload={
                "title": article.title,
                "stage": stage,
                "summary": summary[:1000],
                "links": links or {"Notion": article.notion_url},
                "error_code": error_code,
                "channel": channel,
            },
            next_attempt_at=func.clock_timestamp(),
        )
    )


def _fingerprint(job_id: UUID, event: str, revision: int, error_code: str | None, channel: str | None) -> str:
    value = f"{job_id}:{event}:r{revision}:{error_code or ''}:{channel or ''}"
    return hashlib.sha256(value.encode()).hexdigest()


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


class NotificationOutboxTick:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        notifier: DeliveryNotifier,
        *,
        lease_seconds: int = 30,
        max_backoff_seconds: int = 3600,
        max_batch: int = 50,
    ) -> None:
        self.factory = factory
        self.notifier = notifier
        self.lease_seconds = lease_seconds
        self.max_backoff_seconds = max_backoff_seconds
        self.max_batch = max_batch

    async def __call__(self) -> None:
        for _ in range(self.max_batch):
            claim = await self._claim()
            if claim is None:
                return
            await self._deliver(claim)

    async def _deliver(self, claim: OutboxClaim) -> None:
        try:
            await self.notifier.send(claim.notification)
        except Exception as exc:
            logger.warning("飞书通知失败（error_type=%s）", type(exc).__name__)
            await self._failed(claim, type(exc).__name__)
            return
        await self._sent(claim)

    async def _claim(self) -> OutboxClaim | None:
        async with self.factory.begin() as session:
            now = await database_now(session)
            row = await session.scalar(
                select(NotificationOutbox)
                .where(
                    NotificationOutbox.status == "pending",
                    NotificationOutbox.next_attempt_at <= now,
                    (NotificationOutbox.lease_expires_at.is_(None) | (NotificationOutbox.lease_expires_at < now)),
                )
                .order_by(NotificationOutbox.next_attempt_at, NotificationOutbox.created_at, NotificationOutbox.id)
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
            now = await database_now(session)
            await session.execute(
                update(NotificationOutbox)
                .where(
                    NotificationOutbox.id == claim.id,
                    NotificationOutbox.lease_token == claim.lease_token,
                    NotificationOutbox.lease_expires_at >= now,
                )
                .values(
                    status="sent",
                    attempts=NotificationOutbox.attempts + 1,
                    sent_at=now,
                    lease_token=None,
                    lease_expires_at=None,
                    last_error=None,
                )
            )

    async def _failed(self, claim: OutboxClaim, error_type: str) -> None:
        async with self.factory.begin() as session:
            now = await database_now(session)
            row = await session.scalar(
                select(NotificationOutbox).where(
                    NotificationOutbox.id == claim.id,
                    NotificationOutbox.lease_token == claim.lease_token,
                    NotificationOutbox.lease_expires_at >= now,
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


def _notification(payload: dict[str, object]) -> Notification:
    links = payload.get("links")
    return Notification(
        str(payload.get("title", "")),
        str(payload.get("stage", "")),
        str(payload.get("summary", "")),
        {str(key): str(value) for key, value in links.items()} if isinstance(links, dict) else {},
    )
