"""Persistence access for publication jobs, including atomic lease claims."""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from reven.domain import JobStatus
from reven.jobs.errors import BlockedPublishError, PublishError
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

    async def claim_next(self, *, lease_seconds: int) -> "JobClaim | None":
        """Claim the next due job and set its lease; flushes but does not commit.

        The caller must commit within the same transaction to persist the lease.
        """
        now = datetime.now(tz=UTC)
        statement = (
            select(PublicationJob)
            .where(
                PublicationJob.overall_status.in_([JobStatus.WAITING, JobStatus.PROCESSING]),
                func.coalesce(PublicationJob.snapshot_metadata["notion_write_pending"].astext, "false") != "true",
                func.coalesce(PublicationJob.snapshot_metadata["asset_finalize_pending"].astext, "false") != "true",
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
        job.lease_token = uuid4()
        await self.session.flush()
        return JobClaim(job.id, job.lease_token)

    async def claim_next_preparation_pending(self, *, lease_seconds: int) -> "JobClaim | None":
        """Lock one frozen Job that needs idempotent preparation recovery.

        This does not change status or lease and must never be treated as permission
        to execute publication channels. The caller must pass the Job to prepare().
        """
        now = datetime.now(tz=UTC)
        statement = (
            select(PublicationJob)
            .where(
                PublicationJob.content_hash.is_not(None),
                PublicationJob.overall_status.in_([JobStatus.WAITING, JobStatus.PROCESSING]),
                or_(
                    PublicationJob.snapshot_metadata["notion_write_pending"].astext == "true",
                    PublicationJob.snapshot_metadata["asset_finalize_pending"].astext == "true",
                ),
                PublicationJob.scheduled_at <= now,
                or_(PublicationJob.lease_expires_at.is_(None), PublicationJob.lease_expires_at < now),
            )
            .order_by(PublicationJob.scheduled_at, PublicationJob.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        job: PublicationJob | None = await self.session.scalar(statement)
        if job is None:
            return None
        job.lease_expires_at = now + timedelta(seconds=lease_seconds)
        job.lease_token = uuid4()
        await self.session.flush()
        return JobClaim(job.id, job.lease_token)

    async def renew_lease(self, claim: "JobClaim", *, lease_seconds: int) -> bool:
        now = datetime.now(tz=UTC)
        result = await self.session.execute(
            update(PublicationJob)
            .where(
                PublicationJob.id == claim.job_id,
                PublicationJob.lease_token == claim.lease_token,
                PublicationJob.lease_expires_at >= now,
            )
            .values(lease_expires_at=now + timedelta(seconds=lease_seconds))
        )
        return bool(cast(Any, result).rowcount)

    async def assert_lease(self, claim: "JobClaim") -> bool:
        now = datetime.now(tz=UTC)
        statement = select(PublicationJob.id).where(
            PublicationJob.id == claim.job_id,
            PublicationJob.lease_token == claim.lease_token,
            PublicationJob.lease_expires_at >= now,
        )
        return await self.session.scalar(statement) is not None

    async def set_status_if_leased(self, claim: "JobClaim", status: JobStatus) -> bool:
        now = datetime.now(tz=UTC)
        result = await self.session.execute(
            update(PublicationJob)
            .where(
                PublicationJob.id == claim.job_id,
                PublicationJob.lease_token == claim.lease_token,
                PublicationJob.lease_expires_at >= now,
            )
            .values(overall_status=status)
        )
        return bool(cast(Any, result).rowcount)

    async def release_lease(self, claim: "JobClaim") -> bool:
        result = await self.session.execute(
            update(PublicationJob)
            .where(PublicationJob.id == claim.job_id, PublicationJob.lease_token == claim.lease_token)
            .values(lease_expires_at=None, lease_token=None)
        )
        return bool(cast(Any, result).rowcount)

    async def mark_retry(
        self,
        claim: "JobClaim",
        *,
        delay_seconds: int | None,
        error: PublishError,
    ) -> bool:
        if isinstance(error, BlockedPublishError):
            status = JobStatus.BLOCKED
        else:
            status = JobStatus.WAITING if delay_seconds is not None else JobStatus.FAILED
        values: dict[str, object] = {
            "overall_status": status,
            "lease_expires_at": None,
            "lease_token": None,
        }
        if delay_seconds is not None:
            values["scheduled_at"] = datetime.now(tz=UTC) + timedelta(seconds=delay_seconds)
        result = await self.session.execute(
            update(PublicationJob)
            .where(
                PublicationJob.id == claim.job_id,
                PublicationJob.lease_token == claim.lease_token,
                PublicationJob.lease_expires_at >= datetime.now(tz=UTC),
            )
            .values(**values)
        )
        return bool(cast(Any, result).rowcount)

    async def begin_execution(self, claim: "JobClaim") -> int | None:
        job = await self.session.get(PublicationJob, claim.job_id)
        if (
            job is None
            or job.lease_token != claim.lease_token
            or job.lease_expires_at is None
            or job.lease_expires_at < datetime.now(tz=UTC)
            or job.snapshot_metadata.get("notion_write_pending") is True
            or job.snapshot_metadata.get("asset_finalize_pending") is True
            or job.overall_status != JobStatus.PROCESSING
        ):
            return None
        job.attempt_count += 1
        await self.session.flush()
        return job.attempt_count

    async def record_preparation_attempt(self, claim: "JobClaim") -> int | None:
        job = await self.session.get(PublicationJob, claim.job_id)
        if (
            job is None
            or job.lease_token != claim.lease_token
            or job.lease_expires_at is None
            or job.lease_expires_at < datetime.now(tz=UTC)
        ):
            return None
        metadata = dict(job.snapshot_metadata)
        previous = metadata.get("preparation_attempt_count", 0)
        attempt = previous + 1 if isinstance(previous, int) else 1
        metadata["preparation_attempt_count"] = attempt
        job.snapshot_metadata = metadata
        await self.session.flush()
        return attempt

    async def clear_preparation_attempts(self, claim: "JobClaim") -> None:
        job = await self.session.get(PublicationJob, claim.job_id)
        if (
            job is None
            or job.lease_token != claim.lease_token
            or job.lease_expires_at is None
            or job.lease_expires_at < datetime.now(tz=UTC)
        ):
            return
        metadata = dict(job.snapshot_metadata)
        metadata.pop("preparation_attempt_count", None)
        job.snapshot_metadata = metadata


@dataclass(frozen=True)
class JobClaim:
    job_id: UUID
    lease_token: UUID
