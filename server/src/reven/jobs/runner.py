"""Lifecycle for the two lightweight in-process scheduler loops."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Protocol
from uuid import UUID

import httpx
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.api.routes.sync import _load_notion_config
from reven.config import get_settings
from reven.integrations.notion.client import NotionClient
from reven.integrations.notion.service import NOTION_BASE_URL, REQUEST_TIMEOUT
from reven.integrations.notion.sync import NotionSyncService
from reven.jobs.errors import (
    BlockedPublishError,
    PermanentPublishError,
    PublishError,
    TransientPublishError,
)
from reven.jobs.preparation_models import PrepareResult
from reven.jobs.repository import JobClaim, JobRepository
from reven.jobs.retry import retry_delay_seconds
from reven.jobs.service import (
    NotionStatusWriteError,
    PreparationConflictError,
    PublicationJobService,
)
from reven.publishing.assets import AssetDownloadError, AssetMaterializer

logger = logging.getLogger(__name__)
Tick = Callable[[], Awaitable[None]]


class PreparationService(Protocol):
    async def prepare(self, job_id: UUID) -> object: ...


class JobExecutor(Protocol):
    async def execute(self, job_id: UUID) -> None: ...


class ConfiguredNotionSyncTick:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = session_factory

    async def __call__(self) -> None:
        try:
            token, data_source_id = await _load_notion_config(self._factory)
        except HTTPException as exc:
            logger.warning("跳过 Notion 同步：集成尚未可用（status=%s）", exc.status_code)
            return
        async with httpx.AsyncClient(base_url=NOTION_BASE_URL, timeout=REQUEST_TIMEOUT) as http:
            await NotionSyncService(
                self._factory,
                NotionClient(token=token, http=http),
                data_source_id,
            ).sync_once()


class ConfiguredPreparationService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = session_factory

    async def prepare(self, job_id: UUID) -> PrepareResult:
        token, _ = await _load_notion_config(self._factory)
        settings = get_settings()
        async with httpx.AsyncClient(base_url=NOTION_BASE_URL, timeout=REQUEST_TIMEOUT) as http:
            service = PublicationJobService(
                self._factory,
                NotionClient(token=token, http=http),
                AssetMaterializer(Path(settings.job_data_dir)),
            )
            return await service.prepare(job_id)


def build_background_runner(
    session_factory: async_sessionmaker[AsyncSession],
) -> "BackgroundRunner":
    """Build the Task 8 runner.

    Task 12 injects the channel executor. Until then ``executor=None`` is an
    intentional fail-closed gate: sync and pending recovery run, ordinary
    publication jobs are not claimed.
    """
    settings = get_settings()
    jobs = PublicationJobTick(
        session_factory,
        ConfiguredPreparationService(session_factory),
        executor=None,
        lease_seconds=settings.job_lease_seconds,
    )
    return BackgroundRunner(
        ConfiguredNotionSyncTick(session_factory),
        jobs,
        sync_interval=settings.sync_interval_seconds,
        job_interval=settings.scheduler_interval_seconds,
    )


class _ExecutionError(Exception):
    def __init__(self, error: Exception, attempt: int) -> None:
        self.error = error
        self.attempt = attempt


class _PreparationError(Exception):
    def __init__(self, error: Exception) -> None:
        self.error = error


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
            except Exception as exc:
                logger.error(
                    "后台任务本轮执行失败（tick=%s, error_type=%s）",
                    tick.__class__.__name__,
                    type(exc).__name__,
                )
            await asyncio.sleep(interval)


class PublicationJobTick:
    """One scheduler turn: recover preparation first, then execute one due job."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        preparation: PreparationService,
        executor: JobExecutor | None,
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
        if self._executor is None:
            return
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
            result = await self._preparation.prepare(claim.job_id)
            if isinstance(result, PrepareResult) and result.blocked:
                await self._handle_preparation_failure(claim, BlockedPublishError("准备校验未通过"))
            else:
                await self._clear_preparation_attempts(claim)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._handle_preparation_failure(claim, exc)
        finally:
            await self._release(claim)

    async def _run_execution(self, claim: JobClaim) -> None:
        try:
            await run_until_heartbeat_stops(
                self._execute_claim(claim),
                self._heartbeat(claim),
            )
        except asyncio.CancelledError:
            raise
        except _PreparationError as exc:
            await self._handle_preparation_failure(claim, exc.error)
        except _ExecutionError as exc:
            await self._fail(claim, self._publish_error(exc.error), attempt=exc.attempt)
        except Exception as exc:
            await self._fail(claim, self._publish_error(exc), attempt=1)
        finally:
            await self._release(claim)

    async def _execute_claim(self, claim: JobClaim) -> None:
        try:
            result = await self._preparation.prepare(claim.job_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise _PreparationError(exc) from exc
        if isinstance(result, PrepareResult) and result.blocked:
            raise _PreparationError(BlockedPublishError("准备校验未通过"))
        await self._clear_preparation_attempts(claim)
        attempt = await self._begin_execution(claim)
        if attempt is None or self._executor is None:
            return
        try:
            await self._executor.execute(claim.job_id)
        except Exception as exc:
            raise _ExecutionError(exc, attempt) from exc

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

    async def _record_preparation_attempt(self, claim: JobClaim) -> int | None:
        async with self._factory.begin() as session:
            return await JobRepository(session).record_preparation_attempt(claim)

    async def _clear_preparation_attempts(self, claim: JobClaim) -> None:
        async with self._factory.begin() as session:
            await JobRepository(session).clear_preparation_attempts(claim)

    async def _handle_preparation_failure(
        self,
        claim: JobClaim,
        error: Exception,
    ) -> None:
        classified = self._publish_error(error)
        attempt = 1
        if isinstance(classified, TransientPublishError):
            attempt = await self._record_preparation_attempt(claim) or 1
            if retry_delay_seconds(classified, attempt) is not None:
                await self._fail(claim, classified, attempt=attempt)
                return
        await self._clear_preparation_attempts(claim)
        await self._fail(claim, classified, attempt=attempt)

    async def _release(self, claim: JobClaim) -> None:
        async with self._factory.begin() as session:
            await JobRepository(session).release_lease(claim)

    async def _fail(self, claim: JobClaim, error: PublishError, *, attempt: int) -> None:
        delay = retry_delay_seconds(error, attempt)
        logger.warning(
            "发布任务失败（job_id=%s, category=%s, attempt=%s）",
            claim.job_id,
            type(error).__name__,
            attempt,
        )
        async with self._factory.begin() as session:
            await JobRepository(session).mark_retry(claim, delay_seconds=delay, error=error)

    @staticmethod
    def _publish_error(error: Exception) -> PublishError:
        if isinstance(error, PublishError):
            return error
        if isinstance(error, AssetDownloadError):
            if isinstance(error.__cause__, OSError) or error.code in {
                "download_failed",
                "dns_failed",
                "filesystem_error",
            }:
                return TransientPublishError(error.code)
            return BlockedPublishError(error.code)
        if isinstance(error, HTTPException):
            return BlockedPublishError(f"integration_status_{error.status_code}")
        if isinstance(
            error,
            (
                NotionStatusWriteError,
                PreparationConflictError,
                OSError,
                TimeoutError,
                ConnectionError,
                httpx.TransportError,
            ),
        ):
            return TransientPublishError(type(error).__name__)
        return PermanentPublishError(type(error).__name__)
