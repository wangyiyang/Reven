"""CRM 待跟进每日提醒场景：到期扫描、紧凑中文渲染与逾期天数计算。"""

from datetime import date, timedelta

import pytest
from reven.crm.follow_up_reminder import CrmFollowUpReminder
from reven.crm.repository import CrmRepository
from sqlalchemy.ext.asyncio import AsyncSession

TODAY = date(2026, 9, 30)


async def add_customer(session: AsyncSession, name: str, *, action: str | None, due: date | None) -> None:
    await CrmRepository(session).add_customer({"name": name, "next_action": action, "next_follow_up_on": due})
    await session.commit()


@pytest.mark.anyio
async def test_render_lists_due_customers_with_overdue_days(db_session: AsyncSession) -> None:
    await add_customer(db_session, "远山科技", action="合同续约沟通", due=TODAY - timedelta(days=3))
    await add_customer(db_session, "李明", action="报价确认", due=TODAY - timedelta(days=1))
    await add_customer(db_session, "王芳", action="需求回访", due=TODAY)
    # 未到期与未排期的客户不应出现
    await add_customer(db_session, "未来客户", action="下周约见", due=TODAY + timedelta(days=2))
    await add_customer(db_session, "无排期客户", action=None, due=None)

    content = await CrmFollowUpReminder().render(db_session, TODAY)

    assert content is not None
    lines = content.splitlines()
    assert lines[0] == "9月30日 · 共 3 位客户待跟进（逾期 2 位）"
    # 最逾期在前
    assert lines[2] == "1. 远山科技 — 合同续约沟通（逾期 3 天）"
    assert lines[3] == "2. 李明 — 报价确认（逾期 1 天）"
    assert lines[4] == "3. 王芳 — 需求回访（今日到期）"
    assert "未来客户" not in content
    assert "无排期客户" not in content


@pytest.mark.anyio
async def test_render_returns_none_when_nothing_due(db_session: AsyncSession) -> None:
    await add_customer(db_session, "未来客户", action="下周约见", due=TODAY + timedelta(days=1))

    assert await CrmFollowUpReminder().render(db_session, TODAY) is None


@pytest.mark.anyio
async def test_render_caps_list_and_marks_overflow(db_session: AsyncSession) -> None:
    for index in range(3):
        await add_customer(
            db_session,
            f"客户{index}",
            action="跟进",
            due=TODAY - timedelta(days=index + 1),
        )

    content = await CrmFollowUpReminder(limit=2).render(db_session, TODAY)

    assert content is not None
    assert "共 2+ 位客户待跟进" in content
    # 最逾期（客户2，3 天前到期）在前，最轻（客户0）被截断
    assert "1. 客户2" in content
    assert "客户0" not in content
    assert "……更多请进 CRM 查看。" in content
