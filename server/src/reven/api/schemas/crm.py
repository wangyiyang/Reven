"""Public request and response schemas for CRM."""

import re
from datetime import date, datetime
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator, model_validator

from reven.crm.models import CustomerStatus, FollowUpKind

RequiredName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
OptionalSource = Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=100)]
OptionalRole = Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=100)]
OptionalPhone = Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=50)]
OptionalEmail = Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=320)]
OptionalWechat = Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=100)]
OptionalNotes = Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=10_000)]
OptionalAction = Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=2_000)]
RequiredSummary = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10_000)]
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _empty_to_none(value: object) -> object:
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _validate_email(value: str | None) -> str | None:
    if value is not None and _EMAIL_PATTERN.fullmatch(value) is None:
        raise ValueError("邮箱格式不正确")
    return value


def _require_action_for_date(next_action: str | None, next_follow_up_on: date | None) -> None:
    if next_follow_up_on is not None and not next_action:
        raise ValueError("设置跟进日期时必须提供下一步行动")


class CustomerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: RequiredName
    status: CustomerStatus = CustomerStatus.PROSPECT
    source: OptionalSource = None
    notes: OptionalNotes = None
    next_action: OptionalAction = None
    next_follow_up_on: date | None = None

    _normalize_optional = field_validator("source", "notes", "next_action", mode="before")(_empty_to_none)

    @model_validator(mode="after")
    def validate_action_pair(self) -> Self:
        _require_action_for_date(self.next_action, self.next_follow_up_on)
        return self


class CustomerUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: RequiredName | None = None
    status: CustomerStatus | None = None
    source: OptionalSource = None
    notes: OptionalNotes = None
    next_action: OptionalAction = None
    next_follow_up_on: date | None = None

    _normalize_optional = field_validator("source", "notes", "next_action", mode="before")(_empty_to_none)

    @model_validator(mode="after")
    def keep_required_fields(self) -> Self:
        _reject_explicit_null(self, "name", "status")
        return self


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


class ContactCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: RequiredName
    role: OptionalRole = None
    phone: OptionalPhone = None
    email: OptionalEmail = None
    wechat: OptionalWechat = None
    is_primary: bool = False
    notes: OptionalNotes = None

    _normalize_optional = field_validator("role", "phone", "email", "wechat", "notes", mode="before")(_empty_to_none)
    _email_format = field_validator("email")(_validate_email)


class ContactUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: RequiredName | None = None
    role: OptionalRole = None
    phone: OptionalPhone = None
    email: OptionalEmail = None
    wechat: OptionalWechat = None
    is_primary: bool | None = None
    notes: OptionalNotes = None

    _normalize_optional = field_validator("role", "phone", "email", "wechat", "notes", mode="before")(_empty_to_none)
    _email_format = field_validator("email")(_validate_email)

    @model_validator(mode="after")
    def keep_required_fields(self) -> Self:
        _reject_explicit_null(self, "name")
        return self


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


class FollowUpCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contact_id: UUID | None = None
    kind: FollowUpKind
    occurred_on: date
    summary: RequiredSummary
    next_action: OptionalAction = None
    next_follow_up_on: date | None = None
    set_as_current: bool = False

    _normalize_optional = field_validator("next_action", mode="before")(_empty_to_none)

    @model_validator(mode="after")
    def validate_action_pair(self) -> Self:
        _require_action_for_date(self.next_action, self.next_follow_up_on)
        if self.set_as_current and not self.next_action:
            raise ValueError("同步当前行动时必须提供下一步行动")
        return self


class FollowUpUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contact_id: UUID | None = None
    kind: FollowUpKind | None = None
    occurred_on: date | None = None
    summary: RequiredSummary | None = None
    next_action: OptionalAction = None
    next_follow_up_on: date | None = None

    _normalize_optional = field_validator("next_action", mode="before")(_empty_to_none)

    @model_validator(mode="after")
    def keep_required_fields(self) -> Self:
        _reject_explicit_null(self, "kind", "occurred_on", "summary")
        return self


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


def _reject_explicit_null(model: BaseModel, *fields: str) -> None:
    for field in fields:
        if field in model.model_fields_set and getattr(model, field) is None:
            raise ValueError(f"{field} 不能为 null")
