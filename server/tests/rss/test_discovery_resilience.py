"""#178 RSS 批韧性：checkpoint 断点续跑 / 翻译失败阈值告警 / 死源自动治理。"""

import hashlib
from datetime import UTC, date, datetime

import pytest
from reven.rss.discovery import (
    FeedEntry,
    LocalizedEntry,
    PartialLocalizationError,
    RssDiscoveryService,
)
from reven.rss.models import RssDiscoveryRun, RssItem, RssSource
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

RUN_DATE = date(2026, 9, 1)


def _entry(marker: str) -> FeedEntry:
    published = datetime(2026, 8, 31, 1, tzinfo=UTC)
    return FeedEntry(
        f"guid-{marker}", f"https://example.com/{marker}", f"Title {marker}", f"Summary {marker}", published
    )


class _PerSourceFeed:
    """按 source.id 分发返回条目；fail_on 中的 source 抛错。"""

    def __init__(self, fail_on: set[str] | None = None) -> None:
        self.calls: list[str] = []
        self.fail_on = fail_on or set()

    async def fetch(self, source: RssSource) -> tuple[FeedEntry, ...]:
        self.calls.append(str(source.id))
        if source.name in self.fail_on:
            raise RuntimeError(f"boom-{source.name}")
        return (_entry(source.name),)


class _EchoLocalizer:
    async def localize(self, entries: tuple[FeedEntry, ...]) -> tuple[LocalizedEntry, ...]:
        return tuple(LocalizedEntry(entry, f"中文-{entry.title}", f"摘要-{entry.summary}") for entry in entries)


class _RecordingNotifier:
    def __init__(self) -> None:
        self.notifications: list[object] = []

    async def send(self, notification: object) -> None:
        self.notifications.append(notification)


async def _seed_sources(db_session: AsyncSession, names: list[str]) -> list[RssSource]:
    sources = [RssSource(name=name, feed_url=f"https://example.com/{name}.xml", enabled=True) for name in names]
    db_session.add_all(sources)
    await db_session.commit()
    return sources


@pytest.mark.anyio
async def test_checkpoint_resume_skips_already_processed_sources(db_session: AsyncSession) -> None:
    """同一 run_date 的 running run 重启时跳过 processed_source_ids 已提交源，不重复抓取。"""
    sources = await _seed_sources(db_session, ["alpha", "beta", "gamma"])
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    feed = _PerSourceFeed()
    service = RssDiscoveryService(factory, feed, _EchoLocalizer(), _RecordingNotifier())

    # 第一轮：手动模拟"alpha 已提交、进程中断"——先运行一次完整 run 取出 run_id 太重，直接落库
    run = RssDiscoveryRun(run_date=RUN_DATE, status="running", processed_source_ids=[str(sources[0].id)])
    db_session.add(run)
    await db_session.commit()

    result = await service.run(RUN_DATE)

    assert result.run_id == run.id
    assert result.status == "completed"
    # alpha 已 checkpoint，本轮只抓 beta/gamma
    assert sorted(feed.calls) == sorted([str(sources[1].id), str(sources[2].id)])
    async with factory() as session:
        stored_run = await session.get(RssDiscoveryRun, run.id)
        assert stored_run is not None
        assert sorted(stored_run.processed_source_ids) == sorted(str(s.id) for s in sources)
        # beta/gamma 各入 1 条；alpha 此前中断未提交任何 item，由 checkpoint 保证不重抓
        titles = (await session.scalars(select(RssItem.title))).all()
        assert sorted(titles) == ["Title beta", "Title gamma"]


@pytest.mark.anyio
async def test_failed_source_is_retried_on_next_round_without_resubmitting_completed_ones(
    db_session: AsyncSession,
) -> None:
    """单源失败只影响自己：失败源下轮重抓，已成功源不重复处理。"""
    sources = await _seed_sources(db_session, ["alpha", "beta"])
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    feed = _PerSourceFeed(fail_on={"beta"})
    notifier = _RecordingNotifier()
    service = RssDiscoveryService(factory, feed, _EchoLocalizer(), notifier)

    first = await service.run(RUN_DATE)

    assert first.status == "partial"
    assert first.failure_count == 1
    assert first.fetched_count == 1  # alpha 一条；beta 抛错无条目
    async with factory() as session:
        run = await session.get(RssDiscoveryRun, first.run_id)
        assert run is not None
        # 双源都进 checkpoint（beta 失败也算"已处理"，下一轮不再重试——除非 running 续跑）
        assert sorted(run.processed_source_ids) == sorted(str(s.id) for s in sources)
        beta = await session.get(RssSource, sources[1].id)
        assert beta is not None and beta.consecutive_failures == 1 and beta.last_error == "RuntimeError"

    # 新一轮 date：beta 恢复，checkpoint 全新
    feed.fail_on = set()
    second = await service.run(date(2026, 9, 2))
    assert second.status == "completed"
    async with factory() as session:
        beta = await session.get(RssSource, sources[1].id)
        assert beta is not None and beta.consecutive_failures == 0 and beta.last_error is None


@pytest.mark.anyio
async def test_translation_alert_fires_when_count_threshold_exceeded(db_session: AsyncSession) -> None:
    """翻译失败绝对数超阈值时，汇总后追加一条告警通知；阈值未达不告警。"""
    await _seed_sources(db_session, ["alpha"])
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    class _AllFailingLocalizer:
        async def localize(self, entries: tuple[FeedEntry, ...]) -> tuple[LocalizedEntry, ...]:
            raise RuntimeError("LLM 限速")

    class _MultiEntryFeed:
        async def fetch(self, source: RssSource) -> tuple[FeedEntry, ...]:
            return tuple(_entry(f"post-{index}") for index in range(12))

    notifier = _RecordingNotifier()
    service = RssDiscoveryService(
        factory,
        _MultiEntryFeed(),
        _AllFailingLocalizer(),
        notifier,
        translation_alert_count=10,
        translation_alert_ratio=999.0,  # 关闭占比通道，专测绝对数
    )

    result = await service.run(RUN_DATE)

    assert result.status == "partial"
    assert len(notifier.notifications) == 2
    summary, alert = notifier.notifications
    assert "每日汇总" in summary.title
    assert "翻译失败告警" in alert.title
    assert "12 条" in alert.summary

    # 当日重跑：告警去重，仅补未发的汇总（已发过则什么都不发）
    notifier.notifications.clear()
    await service.run(RUN_DATE)
    assert notifier.notifications == []


@pytest.mark.anyio
async def test_translation_alert_fires_when_ratio_threshold_exceeded(db_session: AsyncSession) -> None:
    """翻译失败占比超阈值即告警，哪怕绝对数不大。"""
    await _seed_sources(db_session, ["alpha"])
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    class _HalfFailingLocalizer:
        async def localize(self, entries: tuple[FeedEntry, ...]) -> tuple[LocalizedEntry, ...]:
            # 与 SiliconFlowChatClient 一致：批级失败用原文填充，error_types 记批级失败次数
            localized = (
                LocalizedEntry(entries[0], "中文标题", "中文摘要"),
                LocalizedEntry(entries[1], entries[1].title, entries[1].summary),
            )
            raise PartialLocalizationError(localized, ("LLM 限速",))

    class _TwoEntryFeed:
        async def fetch(self, source: RssSource) -> tuple[FeedEntry, ...]:
            return (_entry("p1"), _entry("p2"))

    notifier = _RecordingNotifier()
    service = RssDiscoveryService(
        factory,
        _TwoEntryFeed(),
        _HalfFailingLocalizer(),
        notifier,
        translation_alert_count=999,  # 关闭数量通道
        translation_alert_ratio=0.3,
    )

    await service.run(RUN_DATE)

    assert len(notifier.notifications) == 2
    assert "翻译失败告警" in notifier.notifications[1].title
    assert "占比 50%" in notifier.notifications[1].summary


@pytest.mark.anyio
async def test_translation_alert_silenced_below_both_thresholds(db_session: AsyncSession) -> None:
    """数量与占比均未达阈值时不发送告警，仅发每日汇总。"""
    await _seed_sources(db_session, ["alpha"])
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    class _OneFailingLocalizer:
        async def localize(self, entries: tuple[FeedEntry, ...]) -> tuple[LocalizedEntry, ...]:
            # 前 9 条翻译成功，最后 1 条批级失败用原文填充；error_types 仅记 1 次批级失败
            localized = tuple(
                LocalizedEntry(entry, f"中文-{entry.title}", f"中文-{entry.summary}") for entry in entries[:-1]
            ) + (LocalizedEntry(entries[-1], entries[-1].title, entries[-1].summary),)
            raise PartialLocalizationError(localized, ("LLM 限速",))

    class _TenEntryFeed:
        async def fetch(self, source: RssSource) -> tuple[FeedEntry, ...]:
            return tuple(_entry(f"p{index}") for index in range(10))

    notifier = _RecordingNotifier()
    service = RssDiscoveryService(
        factory,
        _TenEntryFeed(),
        _OneFailingLocalizer(),
        notifier,
        translation_alert_count=10,
        translation_alert_ratio=0.3,
    )

    await service.run(RUN_DATE)

    # 1 条失败 / 10 抓取 = 10% 占比，未达 30% 且 1<10 → 不告警
    assert len(notifier.notifications) == 1
    assert "每日汇总" in notifier.notifications[0].title


@pytest.mark.anyio
async def test_dead_source_auto_disabled_after_consecutive_failures(db_session: AsyncSession) -> None:
    """连续 N 轮失败后源被自动禁用并落 disabled_reason；下轮起不再出现在 enabled_sources。"""
    sources = await _seed_sources(db_session, ["flaky"])
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    feed = _PerSourceFeed(fail_on={"flaky"})
    notifier = _RecordingNotifier()
    service = RssDiscoveryService(
        factory,
        feed,
        _EchoLocalizer(),
        notifier,
        source_max_consecutive_failures=3,
    )

    # 连续三轮（三个 run_date）失败
    for day in (1, 2, 3):
        result = await service.run(date(2026, 9, day))
        assert result.failure_count >= 1

    async with factory() as session:
        source = await session.get(RssSource, sources[0].id)
        assert source is not None
        assert source.enabled is False
        assert source.consecutive_failures == 3
        assert source.disabled_at is not None
        assert source.disabled_reason is not None and "连续 3 轮抓取失败" in source.disabled_reason

    # 第三轮应在 errors 中写入 source_governance 记录
    async with factory() as session:
        last_run = await session.scalar(select(RssDiscoveryRun).where(RssDiscoveryRun.run_date == date(2026, 9, 3)))
        assert last_run is not None
        governance = [e for e in last_run.errors if e.get("stage") == "source_governance"]
        assert len(governance) == 1
        assert governance[0]["action"] == "auto_disable"
        assert governance[0]["source_name"] == "flaky"

    # 第四天：源已禁用，不再抓取；当日新 run source_count=0
    fourth = await service.run(date(2026, 9, 4))
    assert fourth.source_count == 0
    assert fourth.fetched_count == 0


@pytest.mark.anyio
async def test_source_recovers_and_clears_failure_counter_before_threshold(db_session: AsyncSession) -> None:
    """未达禁用阈值前一次成功抓取清零计数，不误判死源。"""
    sources = await _seed_sources(db_session, ["flaky"])
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    feed = _PerSourceFeed(fail_on={"flaky"})
    service = RssDiscoveryService(factory, feed, _EchoLocalizer(), _RecordingNotifier())

    await service.run(date(2026, 9, 1))
    await service.run(date(2026, 9, 2))
    async with factory() as session:
        source = await session.get(RssSource, sources[0].id)
        assert source is not None and source.consecutive_failures == 2 and source.enabled is True

    feed.fail_on = set()
    await service.run(date(2026, 9, 3))
    async with factory() as session:
        source = await session.get(RssSource, sources[0].id)
        assert source is not None
        assert source.enabled is True
        assert source.consecutive_failures == 0
        assert source.last_error is None
        assert source.disabled_at is None


@pytest.mark.anyio
async def test_manually_disabled_source_is_not_touched_by_governance(db_session: AsyncSession) -> None:
    """人工禁用的源不进入 enabled_sources，不参与抓取与治理计数。"""
    source = RssSource(name="manual-off", feed_url="https://example.com/off.xml", enabled=False)
    db_session.add(source)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    feed = _PerSourceFeed()
    service = RssDiscoveryService(factory, feed, _EchoLocalizer(), _RecordingNotifier())

    result = await service.run(RUN_DATE)

    assert result.source_count == 0
    assert feed.calls == []


@pytest.mark.anyio
async def test_source_deleted_mid_run_is_skipped_without_checkpoint_pollution(db_session: AsyncSession) -> None:
    """源在事务内被查不到（并发删除）时跳过且不写入 checkpoint，避免历史运行持有悬空 id。"""
    sources = await _seed_sources(db_session, ["ghost"])
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    class _DeletingFeed:
        async def fetch(self, source: RssSource) -> tuple[FeedEntry, ...]:
            # 抓取期间并发删除该源
            async with factory.begin() as session:
                db_source = await session.get(RssSource, source.id)
                if db_source is not None:
                    await session.delete(db_source)
            return (_entry("ghost"),)

    service = RssDiscoveryService(factory, _DeletingFeed(), _EchoLocalizer(), _RecordingNotifier())
    result = await service.run(RUN_DATE)

    async with factory() as session:
        run = await session.get(RssDiscoveryRun, result.run_id)
        assert run is not None
        assert str(sources[0].id) not in run.processed_source_ids


@pytest.mark.anyio
async def test_checkpoint_resume_after_full_crash_leaves_no_duplicate_items(db_session: AsyncSession) -> None:
    """模拟单轮处理到一半被 kill：已提交源不重抓、已落库 item 不重复，下轮补齐剩余源。"""
    sources = await _seed_sources(db_session, ["alpha", "beta", "gamma"])
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    class _CrashingFeed:
        """不依赖源顺序：第 3 次 fetch 调用时抛 KeyboardInterrupt 模拟进程被杀。"""

        def __init__(self) -> None:
            self.calls = 0
            self.fetched_names: list[str] = []

        async def fetch(self, source: RssSource) -> tuple[FeedEntry, ...]:
            self.calls += 1
            if self.calls == 3:
                raise KeyboardInterrupt("模拟进程被杀")
            self.fetched_names.append(source.name)
            return (_entry(source.name),)

    feed = _CrashingFeed()
    service = RssDiscoveryService(factory, feed, _EchoLocalizer(), _RecordingNotifier())

    # KeyboardInterrupt 直接冒泡（不在 fetch 的 Exception 网里）；run 留在 running
    with pytest.raises(KeyboardInterrupt):
        await service.run(RUN_DATE)

    async with factory() as session:
        run = await session.scalar(select(RssDiscoveryRun).where(RssDiscoveryRun.run_date == RUN_DATE))
        assert run is not None and run.status == "running"
        # 前两次 fetch 成功提交 checkpoint；第三次进程被杀未提交
        assert sorted(run.processed_source_ids) == sorted(str(s.id) for s in sources if s.name in feed.fetched_names)
        titles_before = sorted((await session.scalars(select(RssItem.title))).all())
        assert titles_before == sorted(f"Title {name}" for name in feed.fetched_names)

    # 进程重启：新 service 实例；feed 还剩第 3 个源待抓（calls 计数继续，3 不再触发崩溃）
    recovered = RssDiscoveryService(factory, feed, _EchoLocalizer(), _RecordingNotifier())
    result = await recovered.run(RUN_DATE)

    assert result.status == "completed"
    async with factory() as session:
        run = await session.get(RssDiscoveryRun, result.run_id)
        assert run is not None
        assert sorted(run.processed_source_ids) == sorted(str(s.id) for s in sources)
        titles_after = sorted((await session.scalars(select(RssItem.title))).all())
        assert titles_after == ["Title alpha", "Title beta", "Title gamma"]


@pytest.mark.anyio
async def test_summary_includes_disabled_source_in_notification_summary(db_session: AsyncSession) -> None:
    """当日 run 触发自动禁用时，errors 中标注供人工复核；通过 failure_count 反映到每日汇总文案。"""
    sources = await _seed_sources(db_session, ["broken"])
    # 已失败 2 次，再来 1 次即触发禁用阈值 3
    sources[0].consecutive_failures = 2
    db_session.add(sources[0])
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    feed = _PerSourceFeed(fail_on={"broken"})
    notifier = _RecordingNotifier()
    service = RssDiscoveryService(factory, feed, _EchoLocalizer(), notifier, source_max_consecutive_failures=3)

    result = await service.run(RUN_DATE)

    # failure_count = fetch 失败 1 次；source_governance 是动作记录而非失败
    assert result.failure_count == 1
    async with factory() as session:
        run = await session.get(RssDiscoveryRun, result.run_id)
        assert run is not None
        actions = [e for e in run.errors if e.get("stage") == "source_governance"]
        assert len(actions) == 1 and actions[0]["action"] == "auto_disable"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@pytest.mark.anyio
async def test_legacy_run_without_processed_source_ids_backfills_to_empty(db_session: AsyncSession) -> None:
    """0024 之前的 running run 没有 processed_source_ids 值时按空集处理，行为等价于全量重跑。"""
    sources = await _seed_sources(db_session, ["alpha"])
    legacy_run = RssDiscoveryRun(run_date=RUN_DATE, status="running")
    db_session.add(legacy_run)
    await db_session.commit()
    # 直接 UPDATE 模拟历史数据无该字段值（模型 default 仅在 ORM 层生效）
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    feed = _PerSourceFeed()
    service = RssDiscoveryService(factory, feed, _EchoLocalizer(), _RecordingNotifier())

    result = await service.run(RUN_DATE)

    assert result.run_id == legacy_run.id
    assert result.status == "completed"
    assert feed.calls == [str(sources[0].id)]
