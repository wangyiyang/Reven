import hashlib
from datetime import UTC, date, datetime

import pytest
from reven.rss.discovery import FeedEntry, LocalizedEntry, PartialLocalizationError, RssDiscoveryService
from reven.rss.models import RssDiscoveryRun, RssItem, RssSource
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class StubFeedReader:
    def __init__(self) -> None:
        self.calls = 0

    async def fetch(self, source: RssSource) -> tuple[FeedEntry, ...]:
        self.calls += 1
        published = datetime(2026, 8, 11, 1, tzinfo=UTC)
        return (
            FeedEntry("post-1", "https://example.com/post-1", "Agent systems", "First", published),
            FeedEntry("post-1-copy", "https://example.com/post-1", "Agent systems", "Duplicate", published),
        )


class StubLocalizer:
    async def localize(self, entries: tuple[FeedEntry, ...]) -> tuple[LocalizedEntry, ...]:
        return tuple(LocalizedEntry(entry, "智能体系统", "第一篇") for entry in entries)


class RecordingNotifier:
    def __init__(self) -> None:
        self.notifications: list[object] = []

    async def send(self, notification: object) -> None:
        self.notifications.append(notification)


class RecordingScreener:
    def __init__(self, candidate_count: int = 1) -> None:
        self.run_ids: list[object] = []
        self.candidate_count = candidate_count

    async def screen_run(self, run_id: object) -> int:
        self.run_ids.append(run_id)
        return self.candidate_count


class FailingLocalizer:
    async def localize(self, entries: tuple[FeedEntry, ...]) -> tuple[LocalizedEntry, ...]:
        raise RuntimeError("translation unavailable")


class PartiallyFailingLocalizer:
    async def localize(self, entries: tuple[FeedEntry, ...]) -> tuple[LocalizedEntry, ...]:
        localized = (
            LocalizedEntry(entries[0], "已翻译标题", "已翻译摘要"),
            LocalizedEntry(entries[1], entries[1].title, entries[1].summary),
        )
        raise PartialLocalizationError(localized, ("RuntimeError",))


@pytest.mark.anyio
async def test_daily_discovery_is_idempotent_and_sends_one_summary(
    db_session: AsyncSession,
) -> None:
    source = RssSource(name="Example", feed_url="https://example.com/feed.xml", enabled=True)
    db_session.add(source)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    feed = StubFeedReader()
    notifier = RecordingNotifier()
    screener = RecordingScreener()
    service = RssDiscoveryService(factory, feed, StubLocalizer(), notifier, screener=screener)

    first = await service.run(date(2026, 8, 11))
    second = await service.run(date(2026, 8, 11))

    assert second.run_id == first.run_id
    assert first.fetched_count == 2
    assert first.new_count == 1
    assert first.candidate_count == 1
    assert feed.calls == 1
    assert screener.run_ids == [first.run_id]
    assert len(notifier.notifications) == 1
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(RssDiscoveryRun)) == 1
        assert await session.scalar(select(func.count()).select_from(RssItem)) == 1


@pytest.mark.anyio
async def test_translation_failure_is_explicitly_degraded_and_still_notifies(
    db_session: AsyncSession,
) -> None:
    source = RssSource(name="Example", feed_url="https://example.com/other.xml", enabled=True)
    db_session.add(source)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    notifier = RecordingNotifier()
    service = RssDiscoveryService(factory, StubFeedReader(), FailingLocalizer(), notifier)

    result = await service.run(date(2026, 8, 12))

    assert result.status == "partial"
    assert result.failure_count == 1
    assert len(notifier.notifications) == 1
    async with factory() as session:
        item = await session.scalar(select(RssItem))
        run = await session.get(RssDiscoveryRun, result.run_id)
        assert item is not None and run is not None
        assert item.title_zh == item.title
        assert item.summary_zh == item.summary
        assert run.errors == [{"stage": "translation", "error_type": "RuntimeError"}]


@pytest.mark.anyio
async def test_partial_translation_failure_preserves_successful_entries(
    db_session: AsyncSession,
) -> None:
    source = RssSource(name="Example", feed_url="https://example.com/partial.xml", enabled=True)
    db_session.add(source)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    result = await RssDiscoveryService(
        factory,
        StubFeedReader(),
        PartiallyFailingLocalizer(),
        RecordingNotifier(),
    ).run(date(2026, 8, 14))

    assert result.status == "partial"
    assert result.failure_count == 1
    async with factory() as session:
        item = await session.scalar(select(RssItem))
        run = await session.get(RssDiscoveryRun, result.run_id)
        assert item is not None and run is not None
        assert item.title_zh == "已翻译标题"
        assert run.errors == [{"stage": "translation", "error_type": "RuntimeError"}]


@pytest.mark.anyio
async def test_interrupted_running_task_resumes_instead_of_staying_stuck(
    db_session: AsyncSession,
) -> None:
    source = RssSource(name="Example", feed_url="https://example.com/resume.xml", enabled=True)
    interrupted = RssDiscoveryRun(run_date=date(2026, 8, 13), status="running")
    db_session.add_all([source, interrupted])
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    feed = StubFeedReader()
    notifier = RecordingNotifier()

    result = await RssDiscoveryService(factory, feed, StubLocalizer(), notifier).run(interrupted.run_date)

    assert result.run_id == interrupted.id
    assert result.status == "completed"
    assert result.new_count == 1
    assert feed.calls == 1
    assert len(notifier.notifications) == 1


class FlakyNotifier:
    """记录成功投递；fail=True 时抛错（不计投递），模拟发送失败后的重试。"""

    def __init__(self) -> None:
        self.fail = False
        self.attempts = 0
        self.delivered: list[object] = []

    async def send(self, notification: object) -> None:
        self.attempts += 1
        if self.fail:
            raise RuntimeError("notification unavailable")
        self.delivered.append(notification)


@pytest.mark.anyio
async def test_failed_summary_is_retried_on_rerun_without_duplicate_delivery(db_session: AsyncSession) -> None:
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    notifier = FlakyNotifier()
    notifier.fail = True
    service = RssDiscoveryService(factory, StubFeedReader(), StubLocalizer(), notifier)

    first = await service.run(date(2026, 8, 17))

    assert first.status == "completed"
    assert notifier.attempts == 1
    assert notifier.delivered == []
    async with factory() as session:
        run = await session.get(RssDiscoveryRun, first.run_id)
        assert run is not None
        assert run.notification_sent_at is None
        assert run.notification_error == "RuntimeError"

    notifier.fail = False
    second = await service.run(date(2026, 8, 17))

    assert second.run_id == first.run_id
    assert notifier.attempts == 2
    assert len(notifier.delivered) == 1  # 失败重试补发一次，接收人不重复收到
    async with factory() as session:
        run = await session.get(RssDiscoveryRun, first.run_id)
        assert run is not None
        assert run.notification_sent_at is not None
        assert run.notification_error is None


@pytest.mark.anyio
async def test_sent_summary_is_not_resent_on_same_day_rerun(db_session: AsyncSession) -> None:
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    notifier = FlakyNotifier()
    service = RssDiscoveryService(factory, StubFeedReader(), StubLocalizer(), notifier)

    await service.run(date(2026, 8, 18))
    await service.run(date(2026, 8, 18))

    assert notifier.attempts == 1  # notification_sent_at 去重：同日重跑不重发
    assert len(notifier.delivered) == 1


def _backlog_candidate(source: RssSource, run: RssDiscoveryRun, marker: str) -> RssItem:
    return RssItem(
        source_id=source.id,
        first_seen_run_id=run.id,
        source_name=source.name,
        guid=marker,
        url=f"https://example.com/{marker}",
        url_key=hashlib.sha256(f"url-{marker}".encode()).hexdigest(),
        guid_key=hashlib.sha256(f"guid-{marker}".encode()).hexdigest(),
        title_key=hashlib.sha256(f"title-{marker}".encode()).hexdigest(),
        title=f"Title {marker}",
        summary="summary",
        title_zh=f"标题{marker}",
        summary_zh="摘要",
        published_at=datetime(2026, 8, 10, 1, tzinfo=UTC),
        status="candidate",
    )


@pytest.mark.anyio
@pytest.mark.parametrize("backlog", [1, 100, 1000])
async def test_summary_reports_pending_backlog_and_stays_single_message(db_session: AsyncSession, backlog: int) -> None:
    """任意待审核积压量下同一接收人同一天仅收到一条汇总（零审核卡片），含双口径统计与工作台入口。"""
    source = RssSource(name="Example", feed_url=f"https://example.com/backlog-{backlog}.xml", enabled=True)
    backlog_run = RssDiscoveryRun(run_date=date(2026, 8, 10), status="completed")
    db_session.add_all([source, backlog_run])
    await db_session.flush()
    db_session.add_all([_backlog_candidate(source, backlog_run, f"backlog-{index}") for index in range(backlog)])
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    notifier = FlakyNotifier()
    candidate_url = "http://reven.example/rss/candidates"

    result = await RssDiscoveryService(
        factory, StubFeedReader(), StubLocalizer(), notifier, candidate_url=candidate_url
    ).run(date(2026, 8, 19))

    assert result.status == "completed"
    assert len(notifier.delivered) == 1
    notification = notifier.delivered[0]
    assert "候选 0 条" in notification.summary  # 无筛选器时本次新条目为 pending，不计入候选
    assert f"待审核共 {backlog} 条" in notification.summary
    assert notification.links == {"打开候选工作台": candidate_url}

    await RssDiscoveryService(factory, StubFeedReader(), StubLocalizer(), notifier, candidate_url=candidate_url).run(
        date(2026, 8, 19)
    )
    assert len(notifier.delivered) == 1  # 积压场景同日重跑也不重复发送
