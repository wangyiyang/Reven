"""Lifecycle and heartbeat for the in-process RSS discovery loop."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import time
from typing import Protocol

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.config import Settings
from reven.crm.follow_up_reminder import CrmFollowUpReminder
from reven.notify.notifier import FeishuProactiveNotifier
from reven.notify.scheduler import DailyPushConfig, DailyPushScheduler
from reven.provider_clients import FeishuNotifier, ProviderClients
from reven.rss.factory import RssDiscoveryJob
from reven.scheduling import utc_now
from reven.system.models import SystemState

logger = logging.getLogger(__name__)
Tick = Callable[[], Awaitable[None]]


class RunnerProtocol(Protocol):
    async def start(self) -> None: ...

    async def stop(self) -> None: ...


class RssDiscoveryTick:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], tick: Tick) -> None:
        self._factory = session_factory
        self._tick = tick

    async def __call__(self) -> None:
        await self._tick()
        now = utc_now()
        values = {"value": {"last_heartbeat_at": now.isoformat()}, "updated_at": now}
        async with self._factory.begin() as session:
            await session.execute(
                insert(SystemState)
                .values(key="rss_discovery", **values)
                .on_conflict_do_update(index_elements=[SystemState.key], set_=values)
            )


def build_background_runner(
    session_factory: async_sessionmaker[AsyncSession],
    clients: ProviderClients | None,
    settings: Settings | None,
) -> "BackgroundRunner":
    if clients is None or settings is None:
        raise RuntimeError("后台 RSS 任务需要有效的 Settings 与集成凭证")
    notifier = FeishuNotifier(clients)
    rss_tick = RssDiscoveryJob(session_factory, clients, settings, notifier)
    extra_runners: tuple[RunnerProtocol, ...] = ()
    push_scheduler = build_daily_push_scheduler(session_factory, clients, settings)
    if push_scheduler is not None:
        extra_runners = (push_scheduler,)
    return BackgroundRunner(
        RssDiscoveryTick(session_factory, rss_tick),
        rss_interval=settings.rss_scheduler_interval_seconds,
        extra_runners=extra_runners,
    )


def build_daily_push_scheduler(
    session_factory: async_sessionmaker[AsyncSession],
    clients: ProviderClients,
    settings: Settings,
) -> DailyPushScheduler | None:
    """装配定时主动推送服务（#171）：开关关闭时不挂载；首个场景为 CRM 待跟进每日提醒。"""
    if not settings.notify_push_enabled:
        return None
    config = DailyPushConfig(
        enabled=True,
        run_at=time.fromisoformat(settings.notify_push_time),
        chat_id=settings.notify_push_chat_id,
        heartbeat=settings.notify_push_heartbeat,
    )
    return DailyPushScheduler(
        session_factory,
        FeishuProactiveNotifier(clients),
        (CrmFollowUpReminder(),),
        config,
    )


class BackgroundRunner:
    def __init__(
        self,
        rss_tick: Tick,
        *,
        rss_interval: float = 60,
        extra_runners: tuple[RunnerProtocol, ...] = (),
    ) -> None:
        self._rss_tick = rss_tick
        self._rss_interval = rss_interval
        self._extra_runners = extra_runners
        self._tasks: tuple[asyncio.Task[None], ...] = ()

    @property
    def tasks(self) -> tuple[asyncio.Task[None], ...]:
        return self._tasks

    @property
    def healthy(self) -> bool:
        """RSS 主循环任务存活（#177）：任务被取消/异常退出即不健康，供 /api/health 抓 degraded。"""
        return bool(self._tasks) and all(not task.done() for task in self._tasks)

    async def start(self) -> None:
        for runner in self._extra_runners:
            await runner.start()
        if not self._tasks:
            self._tasks = (asyncio.create_task(self._loop(), name="reven-rss-discovery"),)

    async def stop(self) -> None:
        for runner in self._extra_runners:
            await runner.stop()
        tasks, self._tasks = self._tasks, ()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _loop(self) -> None:
        while True:
            try:
                await self._rss_tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("RSS 后台任务本轮执行失败（error_type=%s）", type(exc).__name__)
            await asyncio.sleep(self._rss_interval)
