"""Persistence access for publication jobs, including atomic lease claims."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from reven.domain import JobStatus
from reven.jobs.models import PublicationJob


def compute_target_channels_hash(target_channels: list[str]) -> str:
    normalized = json.dumps(sorted(target_channels), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class JobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_waiting(
        self,
        *,
        article_id: UUID,
        content_hash: str | None,
        target_channels: list[str],
        scheduled_at: datetime,
    ) -> PublicationJob:
        job = PublicationJob(
            article_id=article_id,
            content_hash=content_hash,
            target_channels=target_channels,
            target_channels_hash=compute_target_channels_hash(target_channels),
            overall_status=JobStatus.WAITING,
            blog_status="待处理",
            wechat_status="待处理",
            scheduled_at=scheduled_at,
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def claim_next(self, *, lease_seconds: int) -> PublicationJob | None:
        """Claim the next due job and set its lease; flushes but does not commit.

        The caller must commit within the same transaction to persist the lease.
        """
        now = datetime.now(tz=UTC)
        statement = (
            select(PublicationJob)
            .where(
                PublicationJob.overall_status.in_([JobStatus.WAITING, JobStatus.PROCESSING]),
                PublicationJob.scheduled_at <= now,
                or_(
                    PublicationJob.lease_expires_at.is_(None),
                    PublicationJob.lease_expires_at < now,
                ),
            )
            .order_by(PublicationJob.scheduled_at, PublicationJob.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        job = await self.session.scalar(statement)
        if job is None:
            return None
        job.overall_status = JobStatus.PROCESSING
        job.lease_expires_at = now + timedelta(seconds=lease_seconds)
        await self.session.flush()
        return job
