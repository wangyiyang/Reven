"""通知投递记录的幂等读写：pending 认领 → 投递成功确认 delivered；陈旧 pending 自动回收（#177）。

防丢纪律：认领（claim）只插 pending 占位，绝不等于已投递——容器在投递前崩溃时，
占位行超过 STALE_PENDING_TIMEOUT 未确认即视为崩溃残留，下一次 claim 原子回收重投，
杜绝"认领即提交、崩溃静默丢当日推送"。
"""

from datetime import date, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from reven.notify.models import NotificationLog
from reven.scheduling import utc_now

PENDING_CHANNEL = "pending"
# pending 占位超过该时长未确认 delivered，视为进程崩溃残留，允许回收重投（#177）
STALE_PENDING_TIMEOUT = timedelta(minutes=30)


class NotificationLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def was_delivered(self, biz_key: str, on: date) -> bool:
        """当日是否已确认投递：仅 delivered 行计数；pending 占位（在途/崩溃残留）不算。"""
        statement = select(NotificationLog.id).where(
            NotificationLog.biz_key == biz_key,
            NotificationLog.notified_on == on,
            NotificationLog.channel != PENDING_CHANNEL,
        )
        return (await self._session.scalar(statement)) is not None

    async def claim(self, biz_key: str, on: date, *, now: datetime | None = None) -> bool:
        """认领当日投递权（pending 占位）；认领成功返回 True。

        - 无记录：插入 pending 行，认领成功；
        - 已有 delivered 或新鲜 pending（他人在途投递）：认领失败；
        - 已有陈旧 pending（>= 30 分钟未确认，视为崩溃残留）：原子回收为本次认领（刷新占位时间）。
        """
        claimed_at = now or utc_now()
        stale_before = claimed_at - STALE_PENDING_TIMEOUT
        statement = (
            insert(NotificationLog)
            .values(biz_key=biz_key, notified_on=on, channel=PENDING_CHANNEL, created_at=claimed_at)
            .on_conflict_do_update(
                index_elements=[NotificationLog.biz_key, NotificationLog.notified_on],
                set_={NotificationLog.created_at: claimed_at},
                where=(NotificationLog.channel == PENDING_CHANNEL) & (NotificationLog.created_at < stale_before),
            )
            .returning(NotificationLog.id)
        )
        return (await self._session.scalar(statement)) is not None

    async def mark_channel(self, biz_key: str, on: date, channel: str) -> None:
        """投递成功确认 delivered：回写实际投递通道，当日推送至此完成。"""
        await self._session.execute(
            update(NotificationLog)
            .where(NotificationLog.biz_key == biz_key, NotificationLog.notified_on == on)
            .values(channel=channel)
        )

    async def release(self, biz_key: str, on: date) -> None:
        """释放认领（投递失败/无目标时调用），允许当日后续 tick 重试。"""
        await self._session.execute(
            delete(NotificationLog).where(
                NotificationLog.biz_key == biz_key,
                NotificationLog.notified_on == on,
            )
        )
