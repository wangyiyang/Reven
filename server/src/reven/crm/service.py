"""Transactional CRM mutations and business invariants."""

from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from reven.crm.models import Contact, Customer, FollowUp
from reven.crm.repository import CrmRepository


class InvalidActionPairError(ValueError):
    pass


class ContactNotFoundError(LookupError):
    pass


class CrmService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = CrmRepository(session)

    async def create_customer(self, values: dict[str, object]) -> Customer:
        customer = await self.repository.add_customer(values)
        await self._commit_and_refresh(customer)
        return customer

    async def update_customer(self, customer: Customer, values: dict[str, object]) -> Customer:
        action = values.get("next_action", customer.next_action)
        due_on = values.get("next_follow_up_on", customer.next_follow_up_on)
        if not _valid_action_pair(action, due_on):
            raise InvalidActionPairError
        _assign(customer, values)
        await self._commit_and_refresh(customer)
        return customer

    async def delete_customer(self, customer: Customer) -> None:
        await self.session.delete(customer)
        await self.session.commit()

    async def create_contact(self, customer_id: UUID, values: dict[str, object]) -> Contact:
        if values.get("is_primary") is True:
            await self.repository.clear_primary_contact(customer_id)
        contact = await self.repository.add_contact(customer_id, values)
        await self._commit_and_refresh(contact)
        return contact

    async def update_contact(self, contact: Contact, values: dict[str, object]) -> Contact:
        if values.get("is_primary") is True:
            await self.repository.clear_primary_contact(contact.customer_id)
        _assign(contact, values)
        await self._commit_and_refresh(contact)
        return contact

    async def delete_contact(self, contact: Contact) -> None:
        await self.session.delete(contact)
        await self.session.commit()

    async def create_follow_up(self, customer: Customer, values: dict[str, object]) -> FollowUp:
        set_as_current = bool(values.pop("set_as_current", False))
        contact = await self._contact(customer.id, values.get("contact_id"))
        values["contact_name_snapshot"] = contact.name if contact else None
        follow_up = await self.repository.add_follow_up(customer.id, values)
        if set_as_current:
            customer.next_action = follow_up.next_action
            customer.next_follow_up_on = follow_up.next_follow_up_on
        await self._commit_and_refresh(follow_up)
        return follow_up

    async def update_follow_up(self, follow_up: FollowUp, values: dict[str, object]) -> FollowUp:
        action = values.get("next_action", follow_up.next_action)
        due_on = values.get("next_follow_up_on", follow_up.next_follow_up_on)
        if not _valid_action_pair(action, due_on):
            raise InvalidActionPairError
        if "contact_id" in values:
            contact = await self._contact(follow_up.customer_id, values["contact_id"])
            values["contact_name_snapshot"] = contact.name if contact else None
        _assign(follow_up, values)
        await self._commit_and_refresh(follow_up)
        return follow_up

    async def delete_follow_up(self, follow_up: FollowUp) -> None:
        await self.session.delete(follow_up)
        await self.session.commit()

    async def _contact(self, customer_id: UUID, raw_contact_id: object) -> Contact | None:
        if raw_contact_id is None:
            return None
        if not isinstance(raw_contact_id, UUID):
            raise ContactNotFoundError
        contact = await self.repository.get_contact(customer_id, raw_contact_id)
        if contact is None:
            raise ContactNotFoundError
        return contact

    async def _commit_and_refresh(self, model: Customer | Contact | FollowUp) -> None:
        await self.session.commit()
        await self.session.refresh(model)


def _assign(model: Customer | Contact | FollowUp, values: dict[str, object]) -> None:
    for key, value in values.items():
        setattr(model, key, value)


def _valid_action_pair(action: object, due_on: object) -> bool:
    if due_on is None:
        return True
    return isinstance(due_on, date) and isinstance(action, str) and bool(action)
