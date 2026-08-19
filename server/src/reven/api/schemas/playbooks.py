"""Public schemas for playbooks."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints

PlaybookKind = Literal["sop", "checklist", "script", "method"]
PlaybookStatus = Literal["草稿", "试行", "正式"]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class PlaybookCreate(BaseModel):
    title: Title
    kind: PlaybookKind = "sop"
    status: PlaybookStatus = "草稿"
    body: str = ""
    tags: list[Annotated[str, StringConstraints(strip_whitespace=True, max_length=32)]] = []


class PlaybookUpdate(BaseModel):
    title: Title | None = None
    kind: PlaybookKind | None = None
    status: PlaybookStatus | None = None
    body: str | None = None
    tags: list[Annotated[str, StringConstraints(strip_whitespace=True, max_length=32)]] | None = None


class PlaybookResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    kind: PlaybookKind
    status: PlaybookStatus
    body: str
    tags: list[str]
    created_at: datetime
    updated_at: datetime
