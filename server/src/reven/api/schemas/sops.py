"""Public schemas for SOP entries."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints

SopKind = Literal["procedure", "checklist", "script", "method"]
SopStatus = Literal["草稿", "试行", "正式"]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Body = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class SopCreate(BaseModel):
    title: Title
    kind: SopKind = "procedure"
    status: SopStatus = "草稿"
    body: Body
    tags: list[Annotated[str, StringConstraints(strip_whitespace=True, max_length=32)]] = []


class SopUpdate(BaseModel):
    title: Title | None = None
    kind: SopKind | None = None
    status: SopStatus | None = None
    body: Body | None = None
    tags: list[Annotated[str, StringConstraints(strip_whitespace=True, max_length=32)]] | None = None


class SopResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    kind: SopKind
    status: SopStatus
    body: str
    tags: list[str]
    created_at: datetime
    updated_at: datetime
