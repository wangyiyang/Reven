from datetime import UTC, date, datetime

import pytest
from reven.rss.scheduler import RssScheduleTick


class RecordingDiscovery:
    def __init__(self) -> None:
        self.run_dates: list[date] = []

    async def run(self, run_date: date) -> object:
        self.run_dates.append(run_date)
        return object()


@pytest.mark.anyio
async def test_rss_schedule_starts_at_0600_shanghai() -> None:
    discovery = RecordingDiscovery()
    times = iter(
        (
            datetime(2026, 8, 10, 21, 59, tzinfo=UTC),
            datetime(2026, 8, 10, 22, 0, tzinfo=UTC),
        )
    )
    tick = RssScheduleTick(discovery, clock=lambda: next(times))

    await tick()
    await tick()

    assert discovery.run_dates == [date(2026, 8, 11)]
