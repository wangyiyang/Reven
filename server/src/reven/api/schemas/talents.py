"""Public request and response schemas for talents."""

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from reven.talents.models import InteractionChannel, RateUnit, TalentStatus

RequiredName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
OptionalText = Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=2000)]
Tag = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
RateAmount = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]
Rating = Annotated[int, Field(ge=1, le=5)]
OptionalPhone = Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=50)]
OptionalEmail = Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=320)]
OptionalWechat = Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=100)]

_TEXT_FIELDS = ("organization", "capability", "engagement_terms", "availability", "notes", "phone", "email", "wechat")
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _empty_to_none(value: object) -> object:
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _validate_email(value: str | None) -> str | None:
    if value is not None and _EMAIL_PATTERN.fullmatch(value) is None:
        raise ValueError("邮箱格式不正确")
    return value


def _normalize_string_list(value: object) -> object:
    """preferences：元素 trim、去空、保序去重；非数组/非字符串元素交给 pydantic 报 422。"""
    if not isinstance(value, list):
        return value
    normalized: list[object] = []
    for item in value:
        if isinstance(item, str):
            stripped = item.strip()
            if stripped and stripped not in normalized:
                normalized.append(stripped)
        else:
            normalized.append(item)
    return normalized


def _require_rate_pair(rate_amount: Decimal | None, rate_unit: RateUnit | None) -> None:
    if (rate_amount is None) != (rate_unit is None):
        raise ValueError("费率金额与单位必须同时填写或同时留空")


def _require_date_range(start_on: date | None, end_on: date | None) -> None:
    if start_on is not None and end_on is not None and end_on < start_on:
        raise ValueError("结束日期不能早于开始日期")


def _reject_explicit_null(model: BaseModel, *fields: str) -> None:
    for field in fields:
        if field in model.model_fields_set and getattr(model, field) is None:
            raise ValueError(f"{field} 不能为 null")


class TalentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: RequiredName
    organization: OptionalText = None
    tags: list[Tag] = Field(default_factory=list, max_length=20)
    phone: OptionalPhone = None
    email: OptionalEmail = None
    wechat: OptionalWechat = None
    preferences: list[Tag] = Field(default_factory=list, max_length=20)
    capability: OptionalText = None
    engagement_terms: OptionalText = None
    availability: OptionalText = None
    rate_amount: RateAmount | None = None
    rate_unit: RateUnit | None = None
    rating: Rating | None = None
    status: TalentStatus = TalentStatus.CANDIDATE
    notes: OptionalText = None

    _normalize_optional = field_validator(*_TEXT_FIELDS, mode="before")(_empty_to_none)
    _email_format = field_validator("email")(_validate_email)
    _normalize_preferences = field_validator("preferences", mode="before")(_normalize_string_list)

    @model_validator(mode="after")
    def validate_rate_pair(self) -> Self:
        _require_rate_pair(self.rate_amount, self.rate_unit)
        return self


class TalentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: RequiredName | None = None
    organization: OptionalText = None
    tags: list[Tag] | None = Field(default=None, max_length=20)
    phone: OptionalPhone = None
    email: OptionalEmail = None
    wechat: OptionalWechat = None
    preferences: list[Tag] | None = Field(default=None, max_length=20)
    capability: OptionalText = None
    engagement_terms: OptionalText = None
    availability: OptionalText = None
    rate_amount: RateAmount | None = None
    rate_unit: RateUnit | None = None
    rating: Rating | None = None
    status: TalentStatus | None = None
    notes: OptionalText = None

    _normalize_optional = field_validator(*_TEXT_FIELDS, mode="before")(_empty_to_none)
    _email_format = field_validator("email")(_validate_email)
    _normalize_preferences = field_validator("preferences", mode="before")(_normalize_string_list)

    @model_validator(mode="after")
    def keep_required_fields(self) -> Self:
        _reject_explicit_null(self, "name", "status", "tags", "preferences")
        if {"rate_amount", "rate_unit"} <= self.model_fields_set:
            _require_rate_pair(self.rate_amount, self.rate_unit)
        return self


class TalentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    organization: str | None
    tags: list[str]
    phone: str | None
    email: str | None
    wechat: str | None
    preferences: list[str]
    capability: str | None
    engagement_terms: str | None
    availability: str | None
    rate_amount: Decimal | None
    rate_unit: RateUnit | None
    rating: int | None
    status: TalentStatus
    notes: str | None
    created_at: datetime
    updated_at: datetime


class TalentInteractionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    occurred_on: date
    channel: InteractionChannel
    summary: OptionalText = None
    next_action: OptionalText = None
    next_due_on: date | None = None

    _normalize_optional = field_validator("summary", "next_action", mode="before")(_empty_to_none)


class TalentInteractionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    occurred_on: date | None = None
    channel: InteractionChannel | None = None
    summary: OptionalText = None
    next_action: OptionalText = None
    next_due_on: date | None = None

    _normalize_optional = field_validator("summary", "next_action", mode="before")(_empty_to_none)

    @model_validator(mode="after")
    def keep_required_fields(self) -> Self:
        _reject_explicit_null(self, "occurred_on", "channel")
        return self


class TalentInteractionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    talent_id: UUID
    occurred_on: date
    channel: InteractionChannel
    summary: str | None
    next_action: str | None
    next_due_on: date | None
    created_at: datetime


class TalentExperienceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company: RequiredName
    title: RequiredName
    description: OptionalText = None
    start_on: date
    end_on: date | None = None

    _normalize_optional = field_validator("description", mode="before")(_empty_to_none)

    @model_validator(mode="after")
    def validate_date_range(self) -> Self:
        _require_date_range(self.start_on, self.end_on)
        return self


class TalentExperienceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company: RequiredName | None = None
    title: RequiredName | None = None
    description: OptionalText = None
    start_on: date | None = None
    end_on: date | None = None

    _normalize_optional = field_validator("description", mode="before")(_empty_to_none)

    @model_validator(mode="after")
    def keep_required_fields(self) -> Self:
        _reject_explicit_null(self, "company", "title", "start_on")
        if {"start_on", "end_on"} <= self.model_fields_set:
            _require_date_range(self.start_on, self.end_on)
        return self


class TalentExperienceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    talent_id: UUID
    company: str
    title: str
    description: str | None
    start_on: date
    end_on: date | None
    created_at: datetime
    updated_at: datetime


class TalentEducationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    school: RequiredName
    degree: OptionalText = None
    major: OptionalText = None
    start_on: date
    end_on: date | None = None

    _normalize_optional = field_validator("degree", "major", mode="before")(_empty_to_none)

    @model_validator(mode="after")
    def validate_date_range(self) -> Self:
        _require_date_range(self.start_on, self.end_on)
        return self


class TalentEducationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    school: RequiredName | None = None
    degree: OptionalText = None
    major: OptionalText = None
    start_on: date | None = None
    end_on: date | None = None

    _normalize_optional = field_validator("degree", "major", mode="before")(_empty_to_none)

    @model_validator(mode="after")
    def keep_required_fields(self) -> Self:
        _reject_explicit_null(self, "school", "start_on")
        if {"start_on", "end_on"} <= self.model_fields_set:
            _require_date_range(self.start_on, self.end_on)
        return self


class TalentEducationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    talent_id: UUID
    school: str
    degree: str | None
    major: str | None
    start_on: date
    end_on: date | None
    created_at: datetime
    updated_at: datetime
