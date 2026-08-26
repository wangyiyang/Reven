"""Public request and response schemas for talents."""

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

_TEXT_FIELDS = ("organization", "capability", "engagement_terms", "availability", "notes")


def _empty_to_none(value: object) -> object:
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _require_rate_pair(rate_amount: Decimal | None, rate_unit: RateUnit | None) -> None:
    if (rate_amount is None) != (rate_unit is None):
        raise ValueError("费率金额与单位必须同时填写或同时留空")


def _reject_explicit_null(model: BaseModel, *fields: str) -> None:
    for field in fields:
        if field in model.model_fields_set and getattr(model, field) is None:
            raise ValueError(f"{field} 不能为 null")


class TalentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: RequiredName
    organization: OptionalText = None
    tags: list[Tag] = Field(default_factory=list, max_length=20)
    capability: OptionalText = None
    engagement_terms: OptionalText = None
    availability: OptionalText = None
    rate_amount: RateAmount | None = None
    rate_unit: RateUnit | None = None
    rating: Rating | None = None
    status: TalentStatus = TalentStatus.CANDIDATE
    notes: OptionalText = None

    _normalize_optional = field_validator(*_TEXT_FIELDS, mode="before")(_empty_to_none)

    @model_validator(mode="after")
    def validate_rate_pair(self) -> Self:
        _require_rate_pair(self.rate_amount, self.rate_unit)
        return self


class TalentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: RequiredName | None = None
    organization: OptionalText = None
    tags: list[Tag] | None = Field(default=None, max_length=20)
    capability: OptionalText = None
    engagement_terms: OptionalText = None
    availability: OptionalText = None
    rate_amount: RateAmount | None = None
    rate_unit: RateUnit | None = None
    rating: Rating | None = None
    status: TalentStatus | None = None
    notes: OptionalText = None

    _normalize_optional = field_validator(*_TEXT_FIELDS, mode="before")(_empty_to_none)

    @model_validator(mode="after")
    def keep_required_fields(self) -> Self:
        _reject_explicit_null(self, "name", "status", "tags")
        if {"rate_amount", "rate_unit"} <= self.model_fields_set:
            _require_rate_pair(self.rate_amount, self.rate_unit)
        return self


class TalentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    organization: str | None
    tags: list[str]
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
