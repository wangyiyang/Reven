"""Public request and response schemas for CRM."""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from reven.crm.inputs import ContactCreate as ContactCreate
from reven.crm.inputs import ContactUpdate as ContactUpdate
from reven.crm.inputs import CustomerCreate as CustomerCreate
from reven.crm.inputs import CustomerUpdate as CustomerUpdate
from reven.crm.inputs import FollowUpCreate as FollowUpCreate
from reven.crm.inputs import FollowUpUpdate as FollowUpUpdate
from reven.crm.models import CustomerStatus, FollowUpKind


class CustomerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    status: CustomerStatus
    source: str | None
    notes: str | None
    next_action: str | None
    next_follow_up_on: date | None
    created_at: datetime
    updated_at: datetime


class ContactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    customer_id: UUID
    name: str
    role: str | None
    phone: str | None
    email: str | None
    wechat: str | None
    is_primary: bool
    notes: str | None
    created_at: datetime
    updated_at: datetime


class FollowUpResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    customer_id: UUID
    contact_id: UUID | None
    contact_name_snapshot: str | None
    kind: FollowUpKind
    occurred_on: date
    summary: str
    next_action: str | None
    next_follow_up_on: date | None
    created_at: datetime
    updated_at: datetime
