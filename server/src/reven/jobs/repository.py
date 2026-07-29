"""Persistence access for publication jobs, including atomic lease claims."""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select, update
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

    async def _database_now(self) -> datetime:
        now = await self.session.scalar(select(func.clock_timestamp()))
        if not isinstance(now, datetime):
            raise RuntimeError("数据库未返回有效时间")
        return now

    async def create_waiting(
        self,
        *,
        article_id: UUID,
        content_hash: str | None,
        target_channels: list[str],
        scheduled_at: datetime,
        used_default: bool = False,
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
            snapshot_metadata={"target_channels_used_default": used_default},
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def claim_next(self, *, lease_seconds: int) -> "JobClaim | None":
        """Claim the next due job and set its lease; flushes but does not commit.

        The caller must commit within the same transaction to persist the lease.
        """
        now = await self._database_now()
        statement = (
            select(PublicationJob)
            .where(
                or_(
                    PublicationJob.overall_status.in_([JobStatus.WAITING, JobStatus.PROCESSING]),
                    and_(
                        PublicationJob.overall_status.in_([JobStatus.BLOCKED, JobStatus.FAILED, JobStatus.COMPLETED]),
                        PublicationJob.snapshot_metadata["delivery_finalization"]["notion_pending"].astext == "false",
                    ),
                ),
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
        if "delivery_finalization" not in job.snapshot_metadata:
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
        now = await self._database_now()
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
        now = await self._database_now()
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
        now = await self._database_now()
        statement = select(PublicationJob.id).where(
            PublicationJob.id == claim.job_id,
            PublicationJob.lease_token == claim.lease_token,
            PublicationJob.lease_expires_at >= now,
        )
        return await self.session.scalar(statement) is not None

    async def mark_completed_if_leased(self, claim: "JobClaim") -> bool:
        """Atomically persist legal PROCESSING completion for the lease owner."""
        now = await self._database_now()
        result = await self.session.execute(
            update(PublicationJob)
            .where(
                PublicationJob.id == claim.job_id,
                PublicationJob.lease_token == claim.lease_token,
                PublicationJob.lease_expires_at >= now,
                PublicationJob.overall_status == JobStatus.PROCESSING,
            )
            .values(
                overall_status=JobStatus.COMPLETED,
                finished_at=now,
                lease_token=None,
                lease_expires_at=None,
            )
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
        now = await self._database_now()
        current = await self.session.get(PublicationJob, claim.job_id)
        finalization = current.snapshot_metadata.get("delivery_finalization") if current is not None else None
        if (
            isinstance(finalization, dict)
            and finalization.get("notion_pending") is False
            and current is not None
            and current.overall_status in {JobStatus.BLOCKED, JobStatus.FAILED, JobStatus.COMPLETED}
        ):
            return False
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
            values["scheduled_at"] = now + timedelta(seconds=delay_seconds)
        result = await self.session.execute(
            update(PublicationJob)
            .where(
                PublicationJob.id == claim.job_id,
                PublicationJob.lease_token == claim.lease_token,
                PublicationJob.lease_expires_at >= now,
            )
            .values(**values)
        )
        return bool(cast(Any, result).rowcount)

    async def begin_execution(self, claim: "JobClaim") -> int | None:
        now = await self._database_now()
        job = await self.session.get(PublicationJob, claim.job_id)
        if (
            job is None
            or job.lease_token != claim.lease_token
            or job.lease_expires_at is None
            or job.lease_expires_at < now
            or job.snapshot_metadata.get("notion_write_pending") is True
            or job.snapshot_metadata.get("asset_finalize_pending") is True
            or (job.overall_status != JobStatus.PROCESSING and "delivery_finalization" not in job.snapshot_metadata)
        ):
            return None
        job.attempt_count += 1
        await self.session.flush()
        return job.attempt_count

    async def is_finalization_pending(self, claim: "JobClaim") -> bool:
        now = await self._database_now()
        job = await self.session.get(PublicationJob, claim.job_id)
        return bool(
            job is not None
            and job.lease_token == claim.lease_token
            and job.lease_expires_at is not None
            and job.lease_expires_at >= now
            and "delivery_finalization" in job.snapshot_metadata
        )

    async def bump_notification_revision_for_retry(self, job_id: UUID) -> int | None:
        """人工重试入口：仅在没有有效 worker lease 时递增事件 revision。"""
        now = await self._database_now()
        job = await self.session.scalar(
            select(PublicationJob)
            .where(PublicationJob.id == job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if job is None:
            return None
        if job.lease_token is not None and job.lease_expires_at is not None and job.lease_expires_at >= now:
            return None
        current = job.notification_state.get("_revision", 0)
        revision = (current if isinstance(current, int) else 0) + 1
        job.notification_state = {**job.notification_state, "_revision": revision}
        finalization = job.snapshot_metadata.get("delivery_finalization")
        if isinstance(finalization, dict) and finalization.get("notion_pending") is True:
            job.overall_status = JobStatus.WAITING
            job.scheduled_at = now
        return revision

    async def record_preparation_attempt(self, claim: "JobClaim") -> int | None:
        now = await self._database_now()
        job = await self.session.get(PublicationJob, claim.job_id)
        if (
            job is None
            or job.lease_token != claim.lease_token
            or job.lease_expires_at is None
            or job.lease_expires_at < now
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
        now = await self._database_now()
        job = await self.session.get(PublicationJob, claim.job_id)
        if (
            job is None
            or job.lease_token != claim.lease_token
            or job.lease_expires_at is None
            or job.lease_expires_at < now
        ):
            return
        metadata = dict(job.snapshot_metadata)
        metadata.pop("preparation_attempt_count", None)
        job.snapshot_metadata = metadata


@dataclass(frozen=True)
class JobClaim:
    job_id: UUID
    lease_token: UUID
