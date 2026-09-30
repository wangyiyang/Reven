"""定时主动推送调度：RSS 后台任务同款 asyncio 周期循环 + 每日时刻门。

循环每 check_interval_seconds 醒一次，本地时刻（Asia/Shanghai）过了当日推送点即触发各场景；
幂等由 NotificationLogRepository 认领保证（同一 biz_key 同一自然日只投一次），
容器重启后若当天未推且已过推送时刻，下一轮 tick 自动补推。

失败纪律：
- 配置缺失（机器人未启用/无推送目标）：WARN 一次后静默跳过，释放认领，不刷屏；
- 投递失败：记 error_type 日志并释放认领，当日按 tick 节奏重试，上限 max_attempts_per_day 次后放弃；
- 一切异常不出循环，不影响主服务。
"""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.notify.notifier import ProactiveNotifier, PushTargetMissingError
from reven.notify.repository import NotificationLogRepository
from reven.scheduling import SHANGHAI, utc_now

logger = logging.getLogger(__name__)

DEFAULT_CHECK_INTERVAL_SECONDS = 60.0
DEFAULT_MAX_ATTEMPTS_PER_DAY = 3


class DailyPushScene(Protocol):
    """每日推送场景口：render 返回 markdown 正文；None 表示当日无内容（默认不推）。"""

    biz_key: str
    title: str

    async def render(self, session: AsyncSession, today: date) -> str | None: ...


@dataclass(frozen=True)
class DailyPushConfig:
    enabled: bool
    run_at: time  # Asia/Shanghai 本地时刻
    chat_id: str | None
    heartbeat: bool  # 无内容时是否推送「今日无待办」心跳
    check_interval_seconds: float = DEFAULT_CHECK_INTERVAL_SECONDS
    max_attempts_per_day: int = DEFAULT_MAX_ATTEMPTS_PER_DAY


class DailyPushScheduler:
    """每日定时推送服务：start/stop 生命周期与 BackgroundRunner 对齐（RunnerProtocol）。"""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        notifier: ProactiveNotifier,
        scenes: tuple[DailyPushScene, ...],
        config: DailyPushConfig,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._factory = session_factory
        self._notifier = notifier
        self._scenes = scenes
        self._config = config
        self._clock = clock
        self._task: asyncio.Task[None] | None = None
        self._warned_no_target = False
        self._attempts: dict[tuple[str, date], int] = {}

    async def start(self) -> None:
        if self._config.enabled and self._task is None:
            self._task = asyncio.create_task(self._loop(), name="reven-daily-push")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("定时推送本轮执行失败（error_type=%s）", type(exc).__name__)
            await asyncio.sleep(self._config.check_interval_seconds)

    async def tick(self) -> None:
        """单轮调度：先过时刻门，再逐场景跑「渲染 → 认领 → 投递」。测试可直接驱动。"""
        if not self._config.enabled:
            return
        local_now = self._clock().astimezone(SHANGHAI)
        if local_now.time().replace(tzinfo=None) < self._config.run_at:
            return
        today = local_now.date()
        for scene in self._scenes:
            await self._run_scene(scene, today)

    async def _run_scene(self, scene: DailyPushScene, today: date) -> None:
        async with self._factory.begin() as session:
            repository = NotificationLogRepository(session)
            if await repository.was_notified(scene.biz_key, today):
                return
            if self._attempts.get((scene.biz_key, today), 0) >= self._config.max_attempts_per_day:
                return
            content = await scene.render(session, today)
            if content is None:
                if not self._config.heartbeat:
                    return  # 无内容且未开心跳：不推不认领，当日后续出现内容仍会推
                content = f"✅ {scene.title}：今日无待办事项。"
            if not await repository.claim(scene.biz_key, today):
                return
        try:
            channel = await self._notifier.send_markdown(
                chat_id=self._config.chat_id,
                title=scene.title,
                markdown=content,
                fallback_text=content,
            )
        except PushTargetMissingError as exc:
            if not self._warned_no_target:
                self._warned_no_target = True
                logger.warning("定时推送缺少可用目标，推送暂停直至配置就绪（%s）", exc)
            await self._release(scene.biz_key, today)
            return
        except Exception as exc:
            self._attempts[(scene.biz_key, today)] = self._attempts.get((scene.biz_key, today), 0) + 1
            logger.error("定时推送投递失败（biz_key=%s, error_type=%s）", scene.biz_key, type(exc).__name__)
            await self._release(scene.biz_key, today)
            return
        async with self._factory.begin() as session:
            await NotificationLogRepository(session).mark_channel(scene.biz_key, today, channel)

    async def _release(self, biz_key: str, today: date) -> None:
        try:
            async with self._factory.begin() as session:
                await NotificationLogRepository(session).release(biz_key, today)
        except Exception as exc:
            logger.error("定时推送认领释放失败（biz_key=%s, error_type=%s）", biz_key, type(exc).__name__)
