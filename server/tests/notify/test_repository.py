"""通知投递记录仓储：认领幂等、通道回写与释放。"""

from datetime import date

import pytest
from reven.notify.models import NotificationLog
from reven.notify.repository import PENDING_CHANNEL, NotificationLogRepository
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

ON = date(2026, 9, 30)


@pytest.mark.anyio
async def test_claim_is_idempotent_per_biz_key_and_day(db_session: AsyncSession) -> None:
    repository = NotificationLogRepository(db_session)

    assert await repository.claim("crm:follow-up-daily", ON) is True
    await db_session.commit()

    assert await repository.was_notified("crm:follow-up-daily", ON) is True
    assert await repository.claim("crm:follow-up-daily", ON) is False
    # 换一个自然日或业务键可再次认领
    assert await repository.claim("crm:follow-up-daily", date(2026, 10, 1)) is True
    assert await repository.claim("rss:alert", ON) is True
    await db_session.commit()


@pytest.mark.anyio
async def test_mark_channel_and_release(db_session: AsyncSession) -> None:
    repository = NotificationLogRepository(db_session)
    assert await repository.claim("crm:follow-up-daily", ON) is True
    await db_session.commit()

    await repository.mark_channel("crm:follow-up-daily", ON, "whitelist")
    await db_session.commit()
    fresh = NotificationLogRepository(db_session)
    assert await fresh.was_notified("crm:follow-up-daily", ON) is True

    await fresh.release("crm:follow-up-daily", ON)
    await db_session.commit()
    assert await fresh.was_notified("crm:follow-up-daily", ON) is False
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
