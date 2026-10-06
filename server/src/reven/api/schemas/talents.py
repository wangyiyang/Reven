"""Public request and response schemas for talents."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from reven.talents.inputs import TalentCreate as TalentCreate
from reven.talents.inputs import TalentEducationCreate as TalentEducationCreate
from reven.talents.inputs import TalentEducationUpdate as TalentEducationUpdate
from reven.talents.inputs import TalentExperienceCreate as TalentExperienceCreate
from reven.talents.inputs import TalentExperienceUpdate as TalentExperienceUpdate
from reven.talents.inputs import TalentInteractionCreate as TalentInteractionCreate
from reven.talents.inputs import TalentInteractionUpdate as TalentInteractionUpdate
from reven.talents.inputs import TalentUpdate as TalentUpdate
from reven.talents.models import InteractionChannel, RateUnit, TalentStatus


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
