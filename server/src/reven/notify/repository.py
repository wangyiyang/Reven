"""通知投递记录的幂等读写：认领（claim）先于投递，冲突即跳过。"""

from datetime import date

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from reven.notify.models import NotificationLog

PENDING_CHANNEL = "pending"


class NotificationLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def was_notified(self, biz_key: str, on: date) -> bool:
        statement = select(NotificationLog.id).where(
            NotificationLog.biz_key == biz_key,
            NotificationLog.notified_on == on,
        )
        return (await self._session.scalar(statement)) is not None

    async def claim(self, biz_key: str, on: date) -> bool:
        """认领当日投递权：插入占位行，已被认领（唯一冲突）返回 False。"""
        statement = (
            insert(NotificationLog)
            .values(biz_key=biz_key, notified_on=on, channel=PENDING_CHANNEL)
            .on_conflict_do_nothing()
            .returning(NotificationLog.id)
        )
        return (await self._session.scalar(statement)) is not None

    async def mark_channel(self, biz_key: str, on: date, channel: str) -> None:
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
