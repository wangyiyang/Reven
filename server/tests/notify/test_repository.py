"""通知投递记录仓储：pending 认领幂等、delivered 确认、陈旧 pending 回收（#177）。"""

from datetime import date, timedelta

import pytest
from reven.notify.models import NotificationLog
from reven.notify.repository import PENDING_CHANNEL, STALE_PENDING_TIMEOUT, NotificationLogRepository
from reven.scheduling import utc_now
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

ON = date(2026, 9, 30)


async def _insert_pending(session: AsyncSession, biz_key: str, on: date, *, age: timedelta) -> None:
    """直插一条 pending 占位行（模拟他人在途投递或进程崩溃残留）。"""
    session.add(NotificationLog(biz_key=biz_key, notified_on=on, channel=PENDING_CHANNEL, created_at=utc_now() - age))
    await session.commit()


@pytest.mark.anyio
async def test_claim_is_idempotent_per_biz_key_and_day(db_session: AsyncSession) -> None:
    repository = NotificationLogRepository(db_session)

    assert await repository.claim("crm:follow-up-daily", ON) is True
    await db_session.commit()

    # pending 占位不等于已投递：delivered 视图为 False，新鲜 pending 阻挡二次认领（他人在途）
    assert await repository.was_delivered("crm:follow-up-daily", ON) is False
    assert await repository.claim("crm:follow-up-daily", ON) is False
    # 换一个自然日或业务键可再次认领
    assert await repository.claim("crm:follow-up-daily", date(2026, 10, 1)) is True
    assert await repository.claim("rss:alert", ON) is True
    await db_session.commit()


@pytest.mark.anyio
async def test_mark_channel_confirms_delivered_and_blocks_claim(db_session: AsyncSession) -> None:
    repository = NotificationLogRepository(db_session)
    assert await repository.claim("crm:follow-up-daily", ON) is True
    await db_session.commit()

    await repository.mark_channel("crm:follow-up-daily", ON, "whitelist")
    await db_session.commit()

    fresh = NotificationLogRepository(db_session)
    assert await fresh.was_delivered("crm:follow-up-daily", ON) is True
    assert await fresh.claim("crm:follow-up-daily", ON) is False  # 已确认投递：当日不再认领


@pytest.mark.anyio
async def test_release_allows_reclaim(db_session: AsyncSession) -> None:
    repository = NotificationLogRepository(db_session)
    assert await repository.claim("crm:follow-up-daily", ON) is True
    await db_session.commit()

    await repository.release("crm:follow-up-daily", ON)
    await db_session.commit()

    fresh = NotificationLogRepository(db_session)
    assert await fresh.was_delivered("crm:follow-up-daily", ON) is False
    assert await fresh.claim("crm:follow-up-daily", ON) is True
    await db_session.commit()


@pytest.mark.anyio
async def test_claim_records_pending_channel(db_session: AsyncSession) -> None:
    repository = NotificationLogRepository(db_session)
    assert await repository.claim("crm:follow-up-daily", ON) is True
    await db_session.commit()

    row = (await db_session.scalars(select(NotificationLog))).one()
    assert row.channel == PENDING_CHANNEL
    assert row.biz_key == "crm:follow-up-daily"
    assert row.notified_on == ON


@pytest.mark.anyio
async def test_stale_pending_is_recycled_atomically(db_session: AsyncSession) -> None:
    """崩溃残留的陈旧 pending（≥30 分钟未确认）：claim 原子回收并刷新占位时间（#177）。"""
    await _insert_pending(db_session, "crm:follow-up-daily", ON, age=STALE_PENDING_TIMEOUT + timedelta(minutes=5))
    stale_created_at = (await db_session.scalars(select(NotificationLog))).one().created_at

    repository = NotificationLogRepository(db_session)
    assert await repository.claim("crm:follow-up-daily", ON) is True
    await db_session.commit()

    db_session.expire_all()
    rows = list((await db_session.scalars(select(NotificationLog))).all())
    assert len(rows) == 1  # 回收而非另插新行
    assert rows[0].channel == PENDING_CHANNEL
    assert rows[0].created_at > stale_created_at  # 占位时间已刷新，回收窗口重新计时


@pytest.mark.anyio
async def test_fresh_pending_blocks_claim(db_session: AsyncSession) -> None:
    """新鲜 pending（在回收窗口内）：视为他人在途投递，claim 失败、不回收（#177）。"""
    await _insert_pending(db_session, "crm:follow-up-daily", ON, age=timedelta(minutes=5))

    repository = NotificationLogRepository(db_session)
    assert await repository.claim("crm:follow-up-daily", ON) is False

    db_session.expire_all()
    rows = list((await db_session.scalars(select(NotificationLog))).all())
    assert len(rows) == 1
