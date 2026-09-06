"""Persistence access for finance entries."""

from datetime import date
from uuid import UUID

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from reven.finance.models import FinanceEntry


def _month_bounds(month: str) -> tuple[date, date]:
    start = date.fromisoformat(f"{month}-01")
    if start.month == 12:
        return start, date(start.year + 1, 1, 1)
    return start, date(start.year, start.month + 1, 1)


class FinanceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **values: object) -> FinanceEntry:
        entry = FinanceEntry(**values)
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def get(self, entry_id: UUID) -> FinanceEntry | None:
        return await self.session.get(FinanceEntry, entry_id)

    async def list(
        self,
        *,
        kind: str | None = None,
        query: str | None = None,
        statuses: list[str] | None = None,
        month: str | None = None,
        category: str | None = None,
    ) -> list[FinanceEntry]:
        statement = select(FinanceEntry).order_by(FinanceEntry.occurred_on.desc(), FinanceEntry.created_at.desc())
        if kind:
            statement = statement.where(FinanceEntry.kind == kind)
        if statuses:
            statement = statement.where(FinanceEntry.status.in_(statuses))
        if month:
            start, end = _month_bounds(month)
            statement = statement.where(FinanceEntry.occurred_on >= start, FinanceEntry.occurred_on < end)
        if category:
            statement = statement.where(FinanceEntry.category == category)
        if query:
            statement = statement.where(FinanceEntry.name.ilike(f"%{query}%"))
        result = await self.session.scalars(statement)
        return list(result)

    async def update(self, entry_id: UUID, **values: object) -> FinanceEntry | None:
        entry = await self.get(entry_id)
        if entry is None:
            return None
        for key, value in values.items():
            setattr(entry, key, value)
        await self.session.flush()
        return entry

    async def delete(self, entry_id: UUID) -> bool:
        entry = await self.get(entry_id)
        if entry is None:
            return False
        await self.session.delete(entry)
        await self.session.flush()
        return True

    async def summary(self, *, month: str | None = None) -> dict[str, int]:
        income_condition = and_(FinanceEntry.kind == "income", FinanceEntry.status == "已收")
        expense_condition = and_(FinanceEntry.kind == "expense", FinanceEntry.status == "已付")
        receivable_condition = and_(FinanceEntry.kind == "income", FinanceEntry.status == "应收")
        payable_condition = and_(FinanceEntry.kind == "expense", FinanceEntry.status == "应付")
        if month:
            start, end = _month_bounds(month)
            month_window = and_(FinanceEntry.occurred_on >= start, FinanceEntry.occurred_on < end)
            income_condition = and_(income_condition, month_window)
            expense_condition = and_(expense_condition, month_window)
        income = func.coalesce(func.sum(case((income_condition, FinanceEntry.amount_cents), else_=0)), 0)
        expense = func.coalesce(func.sum(case((expense_condition, FinanceEntry.amount_cents), else_=0)), 0)
        receivable = func.coalesce(func.sum(case((receivable_condition, FinanceEntry.amount_cents), else_=0)), 0)
        payable = func.coalesce(func.sum(case((payable_condition, FinanceEntry.amount_cents), else_=0)), 0)
        row = (await self.session.execute(select(income, expense, receivable, payable))).one()
        income_cents = int(row[0] or 0)
        expense_cents = int(row[1] or 0)
        return {
            "income_cents": income_cents,
            "expense_cents": expense_cents,
            "net_cents": income_cents - expense_cents,
            "receivable_cents": int(row[2] or 0),
            "payable_cents": int(row[3] or 0),
        }
