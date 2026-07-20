"""Postgres queue worker — FOR UPDATE SKIP LOCKED consumer.

任务状态与批次状态同库同事务。
"""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.importing.models import Job, JobStatus

logger = logging.getLogger(__name__)

JobHandler = Callable[[Job, AsyncSession], Coroutine[Any, Any, None]]


async def enqueue_job(
    session: AsyncSession,
    *,
    job_type: str,
    batch_id: UUID | None = None,
    payload: dict[str, object] | None = None,
) -> Job:
    """Enqueue a job for the SKIP LOCKED worker."""
    job = Job(
        job_type=job_type,
        batch_id=batch_id,
        payload=payload,
        status=JobStatus.QUEUED,
        queued_at=datetime.now(UTC),
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


class JobWorker:
    """Worker that polls the job queue with SKIP LOCKED."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        handlers: dict[str, JobHandler] | None = None,
        *,
        poll_interval: float = 1.0,
        max_concurrency: int = 4,
    ) -> None:
        self._session_factory = session_factory
        self._handlers = handlers or {}
        self._poll_interval = poll_interval
        self._max_concurrency = max_concurrency
        self._running = False

    def register_handler(self, job_type: str, handler: JobHandler) -> None:
        """Register a handler for a job type."""
        self._handlers[job_type] = handler

    async def run_forever(self) -> None:
        """Run the worker loop indefinitely."""
        self._running = True
        semaphore = asyncio.Semaphore(self._max_concurrency)

        async def _poll_and_process() -> None:
            async with self._session_factory() as session:
                job = await self._claim_job(session)
                if job is None:
                    return
                async with semaphore:
                    await self._process_job(job)

        while self._running:
            try:
                await _poll_and_process()
                await asyncio.sleep(self._poll_interval)
            except asyncio.CancelledError:
                self._running = False
                break
            except Exception:
                logger.exception("Worker loop error")
                await asyncio.sleep(self._poll_interval * 5)

    async def stop(self) -> None:
        """Signal the worker to stop."""
        self._running = False

    async def _claim_job(self, session: AsyncSession) -> Job | None:
        """Claim one pending job with FOR UPDATE SKIP LOCKED."""
        stmt = (
            select(Job)
            .where(Job.status == JobStatus.QUEUED)
            .where(Job.attempts < Job.max_attempts)
            .order_by(Job.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        result = await session.execute(stmt)
        job = result.scalar_one_or_none()
        if job is not None:
            job.status = JobStatus.RUNNING
            job.started_at = datetime.now(UTC)
            job.attempts += 1
            await session.commit()
        return job

    async def _process_job(self, job: Job) -> None:
        """Execute the handler for a claimed job."""
        handler = self._handlers.get(job.job_type)
        if handler is None:
            logger.warning("No handler for job type: %s", job.job_type)
            await self._fail_job(job.id, f"No handler registered for {job.job_type}")
            return

        try:
            async with self._session_factory() as session:
                await handler(job, session)
                # Refresh job state (handler may have updated it)
                await session.refresh(job)
                if job.status == JobStatus.RUNNING:
                    job.status = JobStatus.COMPLETED
                    job.completed_at = datetime.now(UTC)
                await session.commit()
        except Exception as exc:
            logger.exception("Job %s failed", job.id)
            await self._fail_job(job.id, str(exc))

    async def _fail_job(self, job_id: Any, message: str) -> None:
        """Mark a job as failed (or back to queued if retries remain)."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(Job).where(Job.id == job_id).with_for_update()
            )
            job = result.scalar_one_or_none()
            if job is None:
                return

            if job.attempts >= job.max_attempts:
                job.status = JobStatus.FAILED
                job.completed_at = datetime.now(UTC)
            else:
                job.status = JobStatus.QUEUED
            job.error_message = message[:2000]
            await session.commit()
