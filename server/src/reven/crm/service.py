"""Complete transactional CRM mutations and business invariants."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from reven.crm.errors import ContactNotFoundError, CustomerNotFoundError, FollowUpNotFoundError
from reven.crm.inputs import (
    ContactCreate,
    ContactUpdate,
    CustomerCreate,
    CustomerUpdate,
    FollowUpCreate,
    FollowUpUpdate,
    require_action_for_date,
)
from reven.crm.models import Contact, Customer, FollowUp
from reven.crm.repository import CrmRepository


class CrmService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repository = CrmRepository(session)

    async def create_customer(self, payload: CustomerCreate) -> Customer:
        customer = await self._repository.add_customer(payload.model_dump())
        await self._commit_and_refresh(customer)
        return customer

    async def update_customer(self, customer_id: UUID, payload: CustomerUpdate) -> Customer:
        customer = await self._customer(customer_id)
        _assign(customer, payload.model_dump(exclude_unset=True))
        await self._commit_and_refresh(customer)
        return customer

    async def delete_customer(self, customer_id: UUID) -> Customer:
        customer = await self._customer(customer_id)
        await self._session.delete(customer)
        await self._session.commit()
        return customer

    async def create_contact(self, customer_id: UUID, payload: ContactCreate) -> tuple[Customer, Contact]:
        customer = await self._customer(customer_id)
        if payload.is_primary:
            await self._repository.clear_primary_contact(customer_id)
        contact = await self._repository.add_contact(customer_id, payload.model_dump())
        await self._commit_and_refresh(contact)
        return customer, contact

    async def update_contact(self, customer_id: UUID, contact_id: UUID, payload: ContactUpdate) -> Contact:
        contact = await self._contact(customer_id, contact_id)
        if payload.is_primary is True:
            await self._repository.clear_primary_contact(customer_id)
        _assign(contact, payload.model_dump(exclude_unset=True))
        await self._commit_and_refresh(contact)
        return contact

    async def delete_contact(self, customer_id: UUID, contact_id: UUID) -> Contact:
        contact = await self._contact(customer_id, contact_id)
        await self._session.delete(contact)
        await self._session.commit()
        return contact

    async def create_follow_up(self, customer_id: UUID, payload: FollowUpCreate) -> tuple[Customer, FollowUp]:
        customer = await self._customer(customer_id)
        values = payload.model_dump()
        contact = await self._contact(customer_id, payload.contact_id) if payload.contact_id is not None else None
        values["contact_name_snapshot"] = contact.name if contact else None
        follow_up = await self._repository.add_follow_up(customer_id, values)
        await self._commit_and_refresh(follow_up)
        return customer, follow_up

    async def update_follow_up(self, customer_id: UUID, follow_up_id: UUID, payload: FollowUpUpdate) -> FollowUp:
        follow_up = await self._follow_up(customer_id, follow_up_id)
        _validate_plan(follow_up, payload)
        values = payload.model_dump(exclude_unset=True)
        if "contact_id" in values:
            contact = await self._contact(customer_id, payload.contact_id) if payload.contact_id is not None else None
            values["contact_name_snapshot"] = contact.name if contact else None
        _assign(follow_up, values)
        await self._commit_and_refresh(follow_up)
        return follow_up

    async def delete_follow_up(self, customer_id: UUID, follow_up_id: UUID) -> FollowUp:
        follow_up = await self._follow_up(customer_id, follow_up_id)
        await self._session.delete(follow_up)
        await self._session.commit()
        return follow_up

    async def _customer(self, customer_id: UUID) -> Customer:
        customer = await self._repository.get_customer(customer_id)
        if customer is None:
            raise CustomerNotFoundError(customer_id)
        return customer

    async def _contact(self, customer_id: UUID, contact_id: UUID) -> Contact:
        contact = await self._repository.get_contact(customer_id, contact_id)
        if contact is None:
            raise ContactNotFoundError(contact_id)
        return contact

    async def _follow_up(self, customer_id: UUID, follow_up_id: UUID) -> FollowUp:
        follow_up = await self._repository.get_follow_up(customer_id, follow_up_id)
        if follow_up is None:
            raise FollowUpNotFoundError(follow_up_id)
        return follow_up

    async def _commit_and_refresh(self, model: Customer | Contact | FollowUp) -> None:
        await self._session.commit()
        await self._session.refresh(model)


def _assign(model: Customer | Contact | FollowUp, values: dict[str, object]) -> None:
    for key, value in values.items():
        setattr(model, key, value)


def _validate_plan(current: FollowUp, payload: FollowUpUpdate) -> None:
    action = payload.next_action if "next_action" in payload.model_fields_set else current.next_action
    due_on = payload.next_due_on if "next_due_on" in payload.model_fields_set else current.next_due_on
    require_action_for_date(action, due_on)
