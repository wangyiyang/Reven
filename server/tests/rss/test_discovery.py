from datetime import UTC, date, datetime

import pytest
from reven.rss.discovery import (
    FeedEntry,
    FetchedEntry,
    LocalizedEntry,
    PartialLocalizationError,
    RssDiscoveryService,
)
from reven.rss.models import RssDiscoveryRun, RssSource
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
        self.calls: list[tuple[object, tuple[FetchedEntry, ...]]] = []
        self.candidate_count = candidate_count

    async def screen_run(self, run_id: object, entries: tuple[FetchedEntry, ...]) -> int:
        self.calls.append((run_id, entries))
        return self.candidate_count


class FailingScreener:
    """候选写入失败（Bitable 不可用/未配置）的 run 关键步骤失败 stub；fail 翻转后恢复。"""

    def __init__(self) -> None:
        self.fail = True
        self.calls = 0

    async def screen_run(self, run_id: object, entries: tuple[FetchedEntry, ...]) -> int:
        self.calls += 1
        if self.fail:
            raise RuntimeError("bitable write unavailable")
        return len(entries)


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
    # run 内 seen-set 去重：同 URL 的两条抓取只一条进入筛选
    assert [run_id for run_id, _entries in screener.calls] == [first.run_id]
    assert len(screener.calls[0][1]) == 1
    assert screener.calls[0][1][0].dedupe_key.startswith("url:")
    assert len(notifier.notifications) == 1
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(RssDiscoveryRun)) == 1


@pytest.mark.anyio
async def test_candidate_write_failure_fails_run_without_checkpoint_or_summary(
    db_session: AsyncSession,
) -> None:
    """候选写入失败 = run 失败：status=failed、checkpoint 不推进、不发成功汇总；修复后重试整体重跑。"""
    source = RssSource(name="Example", feed_url="https://example.com/write-fail.xml", enabled=True)
    db_session.add(source)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    feed = StubFeedReader()
    notifier = RecordingNotifier()
    screener = FailingScreener()
    service = RssDiscoveryService(factory, feed, StubLocalizer(), notifier, screener=screener)

    failed = await service.run(date(2026, 8, 15))

    assert failed.status == "failed"
    assert notifier.notifications == []  # 不发成功汇总
    async with factory() as session:
        run = await session.get(RssDiscoveryRun, failed.run_id)
        assert run is not None
        assert run.status == "failed"
        assert run.finished_at is None
        assert run.processed_source_ids == []  # checkpoint 不推进
        assert run.notification_sent_at is None
        assert {"stage": "candidate_write", "error_type": "RuntimeError"} in run.errors

    # 修复后重试：整体重跑（重新抓取），同一 run 恢复为 completed，只发一次汇总
    screener.fail = False
    recovered = await service.run(date(2026, 8, 15))

    assert recovered.run_id == failed.run_id
    assert recovered.status == "completed"
    assert recovered.candidate_count == 1
    assert feed.calls == 2  # checkpoint 已重置，全源重抓
    assert screener.calls == 2
    assert len(notifier.notifications) == 1
    async with factory() as session:
        run = await session.get(RssDiscoveryRun, failed.run_id)
        assert run is not None
        assert run.status == "completed"
        assert run.finished_at is not None


@pytest.mark.anyio
async def test_failed_run_rerun_recovers_without_duplicate_summary(db_session: AsyncSession) -> None:
    """failed run 同日多次重试：成功后汇总仅发一次。"""
    source = RssSource(name="Example", feed_url="https://example.com/retry.xml", enabled=True)
    db_session.add(source)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    notifier = RecordingNotifier()
    screener = FailingScreener()
    service = RssDiscoveryService(factory, StubFeedReader(), StubLocalizer(), notifier, screener=screener)

    await service.run(date(2026, 8, 16))
    await service.run(date(2026, 8, 16))  # 仍失败：重试不发散错误
    screener.fail = False
    await service.run(date(2026, 8, 16))
    await service.run(date(2026, 8, 16))  # 已完成：不再重跑

    assert len(notifier.notifications) == 1
    assert screener.calls == 3


@pytest.mark.anyio
async def test_translation_failure_is_explicitly_degraded_and_still_notifies(
    db_session: AsyncSession,
) -> None:
    source = RssSource(name="Example", feed_url="https://example.com/other.xml", enabled=True)
    db_session.add(source)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    notifier = RecordingNotifier()
    # 调高告警阈值，仅关注"显式降级 + 仍发送汇总"语义；阈值告警由专门用例覆盖
    service = RssDiscoveryService(
        factory,
        StubFeedReader(),
        FailingLocalizer(),
        notifier,
        translation_alert_count=999,
        translation_alert_ratio=999.0,
    )

    result = await service.run(date(2026, 8, 12))

    assert result.status == "partial"
    # #178：整批 localize 失败按条目计数（与生产 rss_discovery_runs 每日 25-35 条 failed 口径一致）
    assert result.failure_count == 2
    assert len(notifier.notifications) == 1
    async with factory() as session:
        run = await session.get(RssDiscoveryRun, result.run_id)
        assert run is not None
        assert run.errors == [
            {"stage": "translation", "error_type": "RuntimeError"},
            {"stage": "translation", "error_type": "RuntimeError"},
        ]


@pytest.mark.anyio
async def test_partial_translation_failure_preserves_successful_entries(
    db_session: AsyncSession,
) -> None:
    source = RssSource(name="Example", feed_url="https://example.com/partial.xml", enabled=True)
    db_session.add(source)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    screener = RecordingScreener()

    result = await RssDiscoveryService(
        factory,
        StubFeedReader(),
        PartiallyFailingLocalizer(),
        RecordingNotifier(),
        screener=screener,
        translation_alert_count=999,
        translation_alert_ratio=999.0,
    ).run(date(2026, 8, 14))

    assert result.status == "partial"
    assert result.failure_count == 1
    async with factory() as session:
        run = await session.get(RssDiscoveryRun, result.run_id)
        assert run is not None
        assert run.errors == [{"stage": "translation", "error_type": "RuntimeError"}]
    # 部分失败时成功条目仍进内存筛选（第一条已翻译）
    assert screener.calls[0][1][0].localized.title_zh == "已翻译标题"


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


@pytest.mark.anyio
@pytest.mark.parametrize("backlog", [1, 100, 1000])
async def test_summary_reports_pending_backlog_and_stays_single_message(db_session: AsyncSession, backlog: int) -> None:
    """任意待审核积压量下同一接收人同一天仅收到一条汇总（零审核卡片），含双口径统计与工作台入口。

    待审核积压数来自 Bitable candidate 计数（生产由 BitableCandidateStore 提供），此处注入计数 stub。
    """
    source = RssSource(name="Example", feed_url=f"https://example.com/backlog-{backlog}.xml", enabled=True)
    db_session.add(source)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    notifier = FlakyNotifier()
    candidate_url = "http://reven.example/rss/candidates"
    counter_calls: list[str] = []

    async def pending_counter(status: str) -> int:
        counter_calls.append(status)
        return backlog

    result = await RssDiscoveryService(
        factory,
        StubFeedReader(),
        StubLocalizer(),
        notifier,
        candidate_url=candidate_url,
        pending_counter=pending_counter,
    ).run(date(2026, 8, 19))

    assert result.status == "completed"
    assert len(notifier.delivered) == 1
    notification = notifier.delivered[0]
    assert "候选 0 条" in notification.summary  # 无筛选管线时不产生候选
    assert f"待审核共 {backlog} 条" in notification.summary
    assert counter_calls == ["candidate"]
    assert notification.links == {"打开候选工作台": candidate_url}

    await RssDiscoveryService(
        factory,
        StubFeedReader(),
        StubLocalizer(),
        notifier,
        candidate_url=candidate_url,
        pending_counter=pending_counter,
    ).run(date(2026, 8, 19))
    assert len(notifier.delivered) == 1  # 积压场景同日重跑也不重复发送


@pytest.mark.anyio
async def test_summary_is_retried_when_pending_count_unavailable(db_session: AsyncSession) -> None:
    """待审核计数失败 = 汇总发送失败：不标记已发送、记录 notification_error、下轮重入重试。"""
    source = RssSource(name="Example", feed_url="https://example.com/count-fail.xml", enabled=True)
    db_session.add(source)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    notifier = FlakyNotifier()
    fail_count = True

    async def pending_counter(status: str) -> int:
        if fail_count:
            raise RuntimeError("bitable count unavailable")
        return 4

    service = RssDiscoveryService(factory, StubFeedReader(), StubLocalizer(), notifier, pending_counter=pending_counter)

    first = await service.run(date(2026, 8, 20))

    assert first.status == "completed"
    assert notifier.delivered == []  # 计数失败时不发汇总
    async with factory() as session:
        run = await session.get(RssDiscoveryRun, first.run_id)
        assert run is not None
        assert run.notification_sent_at is None
        assert run.notification_error == "RuntimeError"

    fail_count = False
    second = await service.run(date(2026, 8, 20))

    assert second.run_id == first.run_id
    assert len(notifier.delivered) == 1
    assert "待审核共 4 条" in notifier.delivered[0].summary
    async with factory() as session:
        run = await session.get(RssDiscoveryRun, first.run_id)
        assert run is not None
        assert run.notification_sent_at is not None
        assert run.notification_error is None
