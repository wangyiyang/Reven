"""Daily 06:00 Asia/Shanghai RSS schedule gate."""

from collections.abc import Callable
from datetime import date, datetime, time
from typing import Protocol
from zoneinfo import ZoneInfo

from reven.scheduling import utc_now

SHANGHAI = ZoneInfo("Asia/Shanghai")
RUN_AT = time(6, 0)


class DiscoveryRunner(Protocol):
    async def run(self, run_date: date) -> object: ...


class RssScheduleTick:
    def __init__(self, discovery: DiscoveryRunner, *, clock: Callable[[], datetime] = utc_now) -> None:
        self._discovery = discovery
        self._clock = clock

    async def __call__(self) -> None:
        local_now = self._clock().astimezone(SHANGHAI)
        if local_now.time().replace(tzinfo=None) < RUN_AT:
            return
        await self._discovery.run(local_now.date())
