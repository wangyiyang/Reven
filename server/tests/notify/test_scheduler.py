"""每日定时推送调度：时刻门、幂等、重启补推、心跳、失败重试与未配置目标纪律。"""

import asyncio
import logging
from datetime import UTC, date, datetime, time, timedelta

import pytest
from reven.notify.models import NotificationLog
from reven.notify.notifier import PushTargetMissingError
from reven.notify.repository import PENDING_CHANNEL
from reven.notify.scheduler import DailyPushConfig, DailyPushScheduler
from reven.scheduling import SHANGHAI, utc_now
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

RUN_AT = time(9, 0)
DAY = date(2026, 9, 30)


class FakeScene:
    biz_key = "test:scene"
    title = "测试场景"

    def __init__(self, content: str | None = "今日内容") -> None:
        self._content = content
        self.renders: list[date] = []

    async def render(self, session: AsyncSession, today: date) -> str | None:
        self.renders.append(today)
        return self._content


class FakeNotifier:
    def __init__(self) -> None:
        self.sent: list[dict[str, str | None]] = []
        self.error: Exception | None = None

    async def send_markdown(self, *, chat_id: str | None, title: str, markdown: str) -> str:
        if self.error is not None:
            raise self.error
        self.sent.append({"chat_id": chat_id, "title": title, "markdown": markdown})
        return "chat"


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=SHANGHAI).astimezone(UTC)


def build_scheduler(
    db_session: AsyncSession,
    scene: FakeScene,
    notifier: FakeNotifier,
    *,
    clock_now: datetime,
    **overrides: object,
) -> DailyPushScheduler:
    values: dict[str, object] = {
        "enabled": True,
        "run_at": RUN_AT,
        "chat_id": "oc_target",
        "heartbeat": False,
        "check_interval_seconds": 3600.0,
    }
    values.update(overrides)
    config = DailyPushConfig(**values)  # type: ignore[arg-type]
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    return DailyPushScheduler(factory, notifier, (scene,), config, clock=lambda: clock_now)


async def notification_rows(db_session: AsyncSession) -> list[NotificationLog]:
    return list((await db_session.scalars(select(NotificationLog))).all())


@pytest.mark.anyio
async def test_before_run_at_does_nothing(db_session: AsyncSession) -> None:
    scene, notifier = FakeScene(), FakeNotifier()
    scheduler = build_scheduler(db_session, scene, notifier, clock_now=at(DAY, 8, 59))

    await scheduler.tick()

    assert scene.renders == []
    assert notifier.sent == []


@pytest.mark.anyio
async def test_at_run_at_renders_and_sends_to_configured_chat(db_session: AsyncSession) -> None:
    scene, notifier = FakeScene(), FakeNotifier()
    scheduler = build_scheduler(db_session, scene, notifier, clock_now=at(DAY, 9, 0))

    await scheduler.tick()

    assert scene.renders == [DAY]
    assert [item["chat_id"] for item in notifier.sent] == ["oc_target"]
    assert notifier.sent[0]["title"] == "测试场景"
    assert notifier.sent[0]["markdown"] == "今日内容"
    rows = await notification_rows(db_session)
    assert [(row.biz_key, row.notified_on, row.channel) for row in rows] == [("test:scene", DAY, "chat")]


@pytest.mark.anyio
async def test_same_day_second_tick_is_idempotent(db_session: AsyncSession) -> None:
    scene, notifier = FakeScene(), FakeNotifier()
    scheduler = build_scheduler(db_session, scene, notifier, clock_now=at(DAY, 9, 0))

    await scheduler.tick()
    await scheduler.tick()

    assert scene.renders == [DAY]
    assert len(notifier.sent) == 1
    assert len(await notification_rows(db_session)) == 1


@pytest.mark.anyio
async def test_restart_after_missed_slot_pushes_once(db_session: AsyncSession) -> None:
    """容器错过时刻重启：新一轮 tick 补推一次；已推过的重启不再重复。"""
    scene, notifier = FakeScene(), FakeNotifier()
    morning = build_scheduler(db_session, scene, notifier, clock_now=at(DAY, 9, 0))
    await morning.tick()
    assert len(notifier.sent) == 1

    # 进程重启 = 全新调度器实例（内存态清零），当天已过时刻但未推的场景应补推
    afternoon_scene = FakeScene()
    afternoon = build_scheduler(db_session, afternoon_scene, notifier, clock_now=at(DAY, 13, 20))
    await afternoon.tick()
    assert len(notifier.sent) == 1  # test:scene 当天已推，不重复

    # 换一个新 biz_key 的场景（模拟重启后新挂载/当天未推过）才会补推
    class OtherScene(FakeScene):
        biz_key = "test:other"

    other = OtherScene()
    restarted = build_scheduler(db_session, other, notifier, clock_now=at(DAY, 13, 21))
    await restarted.tick()
    assert len(notifier.sent) == 2
    assert other.renders == [DAY]


@pytest.mark.anyio
async def test_stale_pending_from_crash_is_recycled_and_redelivered(db_session: AsyncSession) -> None:
    """容器在投递前崩溃（#177 验收）：陈旧 pending 占位（≥30 分钟未确认）被回收，当日重投。"""
    db_session.add(
        NotificationLog(
            biz_key="test:scene",
            notified_on=DAY,
            channel=PENDING_CHANNEL,
            created_at=utc_now() - timedelta(minutes=40),
        )
    )
    await db_session.commit()

    scene, notifier = FakeScene(), FakeNotifier()
    scheduler = build_scheduler(db_session, scene, notifier, clock_now=at(DAY, 9, 0))
    await scheduler.tick()

    assert len(notifier.sent) == 1
    db_session.expire_all()
    rows = await notification_rows(db_session)
    assert [(row.biz_key, row.notified_on, row.channel) for row in rows] == [("test:scene", DAY, "chat")]


@pytest.mark.anyio
async def test_fresh_pending_blocks_tick_redelivery(db_session: AsyncSession) -> None:
    """新鲜 pending（他人在途投递/崩溃未满 30 分钟）：本轮 tick 不重复投递（#177）。"""
    db_session.add(
        NotificationLog(biz_key="test:scene", notified_on=DAY, channel=PENDING_CHANNEL, created_at=utc_now())
    )
    await db_session.commit()

    scene, notifier = FakeScene(), FakeNotifier()
    scheduler = build_scheduler(db_session, scene, notifier, clock_now=at(DAY, 9, 0))
    await scheduler.tick()

    assert notifier.sent == []


@pytest.mark.anyio
async def test_next_day_pushes_again(db_session: AsyncSession) -> None:
    scene, notifier = FakeScene(), FakeNotifier()
    day_one = build_scheduler(db_session, scene, notifier, clock_now=at(DAY, 9, 0))
    await day_one.tick()

    next_day = date(2026, 10, 1)
    day_two = build_scheduler(db_session, scene, notifier, clock_now=at(next_day, 9, 0))
    await day_two.tick()

    assert scene.renders == [DAY, next_day]
    assert len(notifier.sent) == 2
    assert len(await notification_rows(db_session)) == 2


@pytest.mark.anyio
async def test_no_content_skips_push_and_claim_so_late_content_still_goes_out(
    db_session: AsyncSession,
) -> None:
    scene, notifier = FakeScene(content=None), FakeNotifier()
    scheduler = build_scheduler(db_session, scene, notifier, clock_now=at(DAY, 9, 0))

    await scheduler.tick()

    assert notifier.sent == []
    assert await notification_rows(db_session) == []

    # 当天稍后出现内容（如补录的待跟进），下一轮 tick 仍会推
    scene._content = "补录的待跟进"
    later = build_scheduler(db_session, scene, notifier, clock_now=at(DAY, 10, 30))
    await later.tick()
    assert len(notifier.sent) == 1


@pytest.mark.anyio
async def test_heartbeat_pushes_empty_state_only_when_enabled(db_session: AsyncSession) -> None:
    scene, notifier = FakeScene(content=None), FakeNotifier()
    scheduler = build_scheduler(db_session, scene, notifier, clock_now=at(DAY, 9, 0), heartbeat=True)

    await scheduler.tick()

    assert [item["markdown"] for item in notifier.sent] == ["✅ 测试场景：今日无待办事项。"]
    assert len(await notification_rows(db_session)) == 1


@pytest.mark.anyio
async def test_missing_target_warns_once_and_recovers_after_configuration(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    scene, notifier = FakeScene(), FakeNotifier()
    notifier.error = PushTargetMissingError("未配置推送目标")
    scheduler = build_scheduler(db_session, scene, notifier, clock_now=at(DAY, 9, 0))

    with caplog.at_level(logging.WARNING):
        await scheduler.tick()
        await scheduler.tick()

    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1  # 未配置目标只 WARN 一次，不刷屏
    assert notifier.sent == []
    assert await notification_rows(db_session) == []  # 未认领，配置就绪后当日仍可推

    notifier.error = None
    await scheduler.tick()
    assert len(notifier.sent) == 1


@pytest.mark.anyio
async def test_send_failure_retries_with_daily_cap_and_never_breaks_loop(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    scene, notifier = FakeScene(), FakeNotifier()
    notifier.error = RuntimeError("network down token=secret")
    scheduler = build_scheduler(db_session, scene, notifier, clock_now=at(DAY, 9, 0), max_attempts_per_day=3)

    with caplog.at_level(logging.ERROR):
        for _ in range(5):
            await scheduler.tick()

    assert len(scene.renders) == 3  # 当日重试上限后放弃，次日再试
    errors = [record for record in caplog.records if record.levelno == logging.ERROR]
    assert len(errors) == 3
    assert await notification_rows(db_session) == []
    assert "secret" not in caplog.text


@pytest.mark.anyio
async def test_disabled_scheduler_is_inert(db_session: AsyncSession) -> None:
    scene, notifier = FakeScene(), FakeNotifier()
    scheduler = build_scheduler(db_session, scene, notifier, clock_now=at(DAY, 9, 0), enabled=False)

    await scheduler.start()
    assert scheduler._task is None
    await scheduler.tick()

    assert scene.renders == []
    assert notifier.sent == []


@pytest.mark.anyio
async def test_start_stop_lifecycle(db_session: AsyncSession) -> None:
    scheduler = build_scheduler(db_session, FakeScene(content=None), FakeNotifier(), clock_now=at(DAY, 9, 0))

    await scheduler.start()
    await scheduler.start()
    task = scheduler._task
    assert task is not None
    assert task.get_name() == "reven-daily-push"
    await asyncio.sleep(0)  # 让首轮 tick 跑完（无内容 → 进入长 sleep）

    await scheduler.stop()

    assert task.done()
    assert scheduler._task is None
    await scheduler.stop()
