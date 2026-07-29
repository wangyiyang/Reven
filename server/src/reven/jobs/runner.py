"""Lifecycle for the two lightweight in-process scheduler loops."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.jobs.errors import PublishError, TransientPublishError
from reven.jobs.repository import JobClaim, JobRepository
from reven.jobs.retry import retry_delay_seconds

logger = logging.getLogger(__name__)
Tick = Callable[[], Awaitable[None]]


class PreparationService(Protocol):
    async def prepare(self, job_id: UUID) -> object: ...


class JobExecutor(Protocol):
    async def execute(self, job_id: UUID) -> None: ...


async def run_until_heartbeat_stops(
    execution: Awaitable[None],
    heartbeat: Awaitable[None],
) -> None:
    execution_task: asyncio.Future[None] = asyncio.ensure_future(execution)
    heartbeat_task: asyncio.Future[None] = asyncio.ensure_future(heartbeat)
    done, _ = await asyncio.wait(
        (execution_task, heartbeat_task),
        return_when=asyncio.FIRST_COMPLETED,
    )
    if heartbeat_task in done:
        execution_task.cancel()
        await asyncio.gather(execution_task, return_exceptions=True)
        await heartbeat_task
    heartbeat_task.cancel()
    await asyncio.gather(heartbeat_task, return_exceptions=True)
    await execution_task


class BackgroundRunner:
    def __init__(
        self,
        sync_tick: Tick,
        job_tick: Tick,
        *,
        sync_interval: float = 60,
        job_interval: float = 5,
    ) -> None:
        self._sync_tick = sync_tick
        self._job_tick = job_tick
        self._sync_interval = sync_interval
        self._job_interval = job_interval
        self._tasks: tuple[asyncio.Task[None], ...] = ()

    @property
    def tasks(self) -> tuple[asyncio.Task[None], ...]:
        return self._tasks

    async def start(self) -> None:
        if self._tasks:
            return
        self._tasks = (
            asyncio.create_task(self._loop(self._sync_tick, self._sync_interval), name="reven-notion-sync"),
            asyncio.create_task(self._loop(self._job_tick, self._job_interval), name="reven-job-runner"),
        )

    async def stop(self) -> None:
        tasks, self._tasks = self._tasks, ()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _loop(self, tick: Tick, interval: float) -> None:
        while True:
            try:
                await tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("后台任务本轮执行失败（%s）", tick.__class__.__name__)
            await asyncio.sleep(interval)


class PublicationJobTick:
    """One scheduler turn: recover preparation first, then execute one due job."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        preparation: PreparationService,
        executor: JobExecutor,
        *,
        lease_seconds: int = 120,
        heartbeat_seconds: float = 30,
    ) -> None:
        self._factory = session_factory
        self._preparation = preparation
        self._executor = executor
        self._lease_seconds = lease_seconds
        self._heartbeat_seconds = heartbeat_seconds

    async def __call__(self) -> None:
        preparation_claim = await self._claim(preparation=True)
        if preparation_claim is not None:
            await self._run_preparation(preparation_claim)
        claim = await self._claim(preparation=False)
        if claim is not None:
            await self._run_execution(claim)

    async def _claim(self, *, preparation: bool) -> JobClaim | None:
        async with self._factory.begin() as session:
            repository = JobRepository(session)
            if preparation:
                return await repository.claim_next_preparation_pending(lease_seconds=self._lease_seconds)
            return await repository.claim_next(lease_seconds=self._lease_seconds)

    async def _run_preparation(self, claim: JobClaim) -> None:
        try:
            await self._preparation.prepare(claim.job_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._fail(claim, self._publish_error(exc), attempt=1)
        else:
            await self._release(claim)

    async def _run_execution(self, claim: JobClaim) -> None:
        try:
            await run_until_heartbeat_stops(
                self._execute_claim(claim),
                self._heartbeat(claim),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._fail(claim, self._publish_error(exc), attempt=1)
        finally:
            await self._release(claim)

    async def _execute_claim(self, claim: JobClaim) -> None:
        await self._preparation.prepare(claim.job_id)
        attempt = await self._begin_execution(claim)
        if attempt is not None:
            await self._executor.execute(claim.job_id)

    async def _heartbeat(self, claim: JobClaim) -> None:
        while True:
            await asyncio.sleep(self._heartbeat_seconds)
            async with self._factory.begin() as session:
                renewed = await JobRepository(session).renew_lease(claim, lease_seconds=self._lease_seconds)
            if not renewed:
                raise TransientPublishError("发布任务租约已丢失")

    async def _begin_execution(self, claim: JobClaim) -> int | None:
        async with self._factory.begin() as session:
            return await JobRepository(session).begin_execution(claim)

    async def _release(self, claim: JobClaim) -> None:
        async with self._factory.begin() as session:
            await JobRepository(session).release_lease(claim)

    async def _fail(self, claim: JobClaim, error: PublishError, *, attempt: int) -> None:
        delay = retry_delay_seconds(error, attempt)
        async with self._factory.begin() as session:
            await JobRepository(session).mark_retry(claim, delay_seconds=delay, error=error)

    @staticmethod
    def _publish_error(error: Exception) -> PublishError:
        if isinstance(error, PublishError):
            return error
        return TransientPublishError(type(error).__name__)
