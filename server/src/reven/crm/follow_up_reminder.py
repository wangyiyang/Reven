"""CRM 待跟进每日提醒：DailyPushScene 的首个挂载场景。

扫描 next_follow_up_on <= 今天（Asia/Shanghai）的客户，渲染紧凑中文清单
（客户名、跟进事项、逾期天数）；无待跟进返回 None（默认不骚扰）。
"""

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from reven.crm.models import Customer
from reven.crm.repository import CrmRepository

DEFAULT_LIMIT = 20


class CrmFollowUpReminder:
    biz_key = "crm:follow-up-daily"
    title = "CRM 待跟进提醒"

    def __init__(self, *, limit: int = DEFAULT_LIMIT) -> None:
        self._limit = limit

    async def render(self, session: AsyncSession, today: date) -> str | None:
        customers = await CrmRepository(session).list_due_follow_ups(today=today, limit=self._limit + 1)
        if not customers:
            return None
        overflow = len(customers) > self._limit
        shown = customers[: self._limit]
        overdue_count = sum(
            1 for customer in shown if customer.next_follow_up_on is not None and customer.next_follow_up_on < today
        )
        header = f"共 {len(shown)}{'+' if overflow else ''} 位客户待跟进"
        if overdue_count:
            header += f"（逾期 {overdue_count} 位）"
        lines = [f"{today.month}月{today.day}日 · {header}", ""]
        lines.extend(f"{index}. {self._format_line(customer, today)}" for index, customer in enumerate(shown, 1))
        if overflow:
            lines.append("")
            lines.append("……更多请进 CRM 查看。")
        return "\n".join(lines)

    @staticmethod
    def _format_line(customer: Customer, today: date) -> str:
        action = (customer.next_action or "").strip() or "（未填跟进事项）"
        due = customer.next_follow_up_on
        if due is None or due >= today:
            badge = "今日到期"
        else:
            badge = f"逾期 {(today - due).days} 天"
        return f"{customer.name} — {action}（{badge}）"
