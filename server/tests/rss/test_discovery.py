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


class RecordingReviewPusher:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls = 0
        self._fail = fail

    async def push_pending_review(self) -> None:
        self.calls += 1
        if self._fail:
            raise RuntimeError("review push unavailable")


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


@pytest.mark.anyio
async def test_review_card_pusher_runs_after_summary_notification(
    db_session: AsyncSession,
) -> None:
    source = RssSource(name="Example", feed_url="https://example.com/review-push.xml", enabled=True)
    db_session.add(source)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    notifier = RecordingNotifier()
    review_pusher = RecordingReviewPusher()

    result = await RssDiscoveryService(
        factory,
        StubFeedReader(),
        StubLocalizer(),
        notifier,
        review_pusher=review_pusher,
    ).run(date(2026, 8, 15))

    assert result.status == "completed"
    assert len(notifier.notifications) == 1
    assert review_pusher.calls == 1


@pytest.mark.anyio
async def test_review_card_pusher_failure_does_not_affect_run_or_notification(
    db_session: AsyncSession,
) -> None:
    source = RssSource(name="Example", feed_url="https://example.com/review-push-fail.xml", enabled=True)
    db_session.add(source)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    notifier = RecordingNotifier()
    review_pusher = RecordingReviewPusher(fail=True)

    result = await RssDiscoveryService(
        factory,
        StubFeedReader(),
        StubLocalizer(),
        notifier,
        review_pusher=review_pusher,
    ).run(date(2026, 8, 16))

    assert result.status == "completed"
    assert review_pusher.calls == 1
    assert len(notifier.notifications) == 1
    async with factory() as session:
        run = await session.get(RssDiscoveryRun, result.run_id)
        assert run is not None
        assert run.notification_sent_at is not None  # 推送失败不影响汇总通知标记
        assert run.notification_error is None
