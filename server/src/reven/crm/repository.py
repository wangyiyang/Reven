"""Persistence queries for CRM customers, contacts, and follow-ups."""

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import ScalarSelect, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from reven.crm.models import Contact, Customer, FollowUp
from reven.db import escape_like
from reven.scheduling import utc_now


@dataclass(frozen=True)
class CustomerPlan:
    """客户与其派生当前计划：最新一条跟进记录（occurred_on/created_at/id 倒序）的下一步行动与到期日。"""

    customer: Customer
    next_action: str | None
    next_due_on: date | None


def _latest_action_subquery() -> ScalarSelect[str | None]:
    return (
        select(FollowUp.next_action)
        .where(FollowUp.customer_id == Customer.id)
        .order_by(FollowUp.occurred_on.desc(), FollowUp.created_at.desc(), FollowUp.id.desc())
        .limit(1)
        .correlate(Customer)
        .scalar_subquery()
    )


def _latest_due_subquery() -> ScalarSelect[date | None]:
    return (
        select(FollowUp.next_due_on)
        .where(FollowUp.customer_id == Customer.id)
        .order_by(FollowUp.occurred_on.desc(), FollowUp.created_at.desc(), FollowUp.id.desc())
        .limit(1)
        .correlate(Customer)
        .scalar_subquery()
    )


class CrmRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_customers(
        self,
        *,
        status: str | None,
        due: str | None,
        query: str | None,
        today: date,
    ) -> list[CustomerPlan]:
        latest_action = _latest_action_subquery()
        latest_due = _latest_due_subquery()
        statement = select(Customer, latest_action, latest_due)
        if status:
            statement = statement.where(Customer.status == status)
        statement = self._filter_due(statement, due, today)
        if query:
            statement = statement.where(self._customer_search(query))
        statement = statement.order_by(
            latest_due.is_(None),
            latest_due,
            Customer.updated_at.desc(),
            func.lower(Customer.name),
        )
        rows = (await self.session.execute(statement)).all()
        return [CustomerPlan(customer=row[0], next_action=row[1], next_due_on=row[2]) for row in rows]

    @staticmethod
    def _filter_due(statement, due: str | None, today: date):  # type: ignore[no-untyped-def]
        latest_due = _latest_due_subquery()
        if due == "overdue":
            return statement.where(latest_due < today)
        if due == "today":
            return statement.where(latest_due == today)
        if due == "upcoming":
            return statement.where(latest_due > today)
        if due == "none":
            return statement.where(latest_due.is_(None))
        return statement

    @staticmethod
    def _customer_search(query: str):  # type: ignore[no-untyped-def]
        pattern = f"%{escape_like(query)}%"
        contact_match = exists(
            select(Contact.id).where(
                Contact.customer_id == Customer.id,
                or_(
                    Contact.name.ilike(pattern, escape="\\"),
                    Contact.role.ilike(pattern, escape="\\"),
                    Contact.phone.ilike(pattern, escape="\\"),
                    Contact.email.ilike(pattern, escape="\\"),
                    Contact.wechat.ilike(pattern, escape="\\"),
                    Contact.notes.ilike(pattern, escape="\\"),
                ),
            )
        )
        return or_(
            Customer.name.ilike(pattern, escape="\\"),
            Customer.source.ilike(pattern, escape="\\"),
            Customer.notes.ilike(pattern, escape="\\"),
            contact_match,
        )

    async def get_customer_plan(self, customer_id: UUID) -> CustomerPlan | None:
        """单个客户 + 派生当前计划；客户不存在返回 None。"""
        statement = select(Customer, _latest_action_subquery(), _latest_due_subquery()).where(
            Customer.id == customer_id
        )
        row = (await self.session.execute(statement)).one_or_none()
        if row is None:
            return None
        return CustomerPlan(customer=row[0], next_action=row[1], next_due_on=row[2])

    async def list_due_follow_ups(self, *, today: date, limit: int) -> list[CustomerPlan]:
        """到期/逾期未跟进客户：派生 next_due_on <= 今天，按到期日升序（最逾期在前）。"""
        latest_action = _latest_action_subquery()
        latest_due = _latest_due_subquery()
        statement = (
            select(Customer, latest_action, latest_due)
            .where(latest_due.is_not(None), latest_due <= today)
            .order_by(latest_due, func.lower(Customer.name))
            .limit(limit)
        )
        rows = (await self.session.execute(statement)).all()
        return [CustomerPlan(customer=row[0], next_action=row[1], next_due_on=row[2]) for row in rows]

    async def count_due_follow_ups(self, *, today: date) -> tuple[int, int]:
        """派生到期日 < / == 今天的客户数（overdue_count, today_count），与 list_due_follow_ups 同源。"""
        latest_due = _latest_due_subquery()
        row = (
            await self.session.execute(
                select(
                    func.count().filter(latest_due < today),
                    func.count().filter(latest_due == today),
                ).select_from(Customer)
            )
        ).one()
        return int(row[0]), int(row[1])

    async def get_customer(self, customer_id: UUID) -> Customer | None:
        return await self.session.get(Customer, customer_id)

    async def add_customer(self, values: dict[str, object]) -> Customer:
        customer = Customer(**values)
        self.session.add(customer)
        await self.session.flush()
        return customer

    async def list_contacts(self, customer_id: UUID) -> list[Contact]:
        statement = (
            select(Contact)
            .where(Contact.customer_id == customer_id)
            .order_by(Contact.is_primary.desc(), func.lower(Contact.name), Contact.created_at)
        )
        return list((await self.session.scalars(statement)).all())

    async def get_contact(self, customer_id: UUID, contact_id: UUID) -> Contact | None:
        statement = select(Contact).where(Contact.id == contact_id, Contact.customer_id == customer_id)
        result = await self.session.scalars(statement)
        return result.one_or_none()

    async def clear_primary_contact(self, customer_id: UUID) -> None:
        await self.session.execute(
            update(Contact)
            .where(Contact.customer_id == customer_id, Contact.is_primary.is_(True))
            .values(is_primary=False, updated_at=utc_now())
        )

    async def add_contact(self, customer_id: UUID, values: dict[str, object]) -> Contact:
        contact = Contact(customer_id=customer_id, **values)
        self.session.add(contact)
        await self.session.flush()
        return contact

    async def list_follow_ups(self, customer_id: UUID) -> list[FollowUp]:
        statement = (
            select(FollowUp)
            .where(FollowUp.customer_id == customer_id)
            .order_by(FollowUp.occurred_on.desc(), FollowUp.created_at.desc())
        )
        return list((await self.session.scalars(statement)).all())

    async def get_follow_up(self, customer_id: UUID, follow_up_id: UUID) -> FollowUp | None:
        statement = select(FollowUp).where(
            FollowUp.id == follow_up_id,
            FollowUp.customer_id == customer_id,
        )
        result = await self.session.scalars(statement)
        return result.one_or_none()

    async def add_follow_up(self, customer_id: UUID, values: dict[str, object]) -> FollowUp:
        follow_up = FollowUp(customer_id=customer_id, **values)
        self.session.add(follow_up)
        await self.session.flush()
        return follow_up
