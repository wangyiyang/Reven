"""Lifecycle and heartbeat for the in-process RSS discovery loop."""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.config import get_settings
from reven.notifications import build_configured_notifier
from reven.rss.factory import build_configured_rss_tick
from reven.scheduling import utc_now
from reven.system.models import SystemState

logger = logging.getLogger(__name__)
Tick = Callable[[], Awaitable[None]]


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


def build_background_runner(session_factory: async_sessionmaker[AsyncSession]) -> "BackgroundRunner":
    settings = get_settings()
    notifier = build_configured_notifier(session_factory, settings)
    rss_tick = build_configured_rss_tick(session_factory, settings, notifier)
    return BackgroundRunner(
        RssDiscoveryTick(session_factory, rss_tick),
        rss_interval=settings.rss_scheduler_interval_seconds,
    )


class BackgroundRunner:
    def __init__(self, rss_tick: Tick, *, rss_interval: float = 60) -> None:
        self._rss_tick = rss_tick
        self._rss_interval = rss_interval
        self._tasks: tuple[asyncio.Task[None], ...] = ()

    @property
    def tasks(self) -> tuple[asyncio.Task[None], ...]:
        return self._tasks

    async def start(self) -> None:
        if not self._tasks:
            self._tasks = (asyncio.create_task(self._loop(), name="reven-rss-discovery"),)

    async def stop(self) -> None:
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
