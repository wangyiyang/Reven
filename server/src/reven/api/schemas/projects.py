"""Public schemas for projects."""

from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
OptionalShortText = Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=200)]


class ProjectCreate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    goal: str | None = None
    status: Annotated[str, StringConstraints(strip_whitespace=True, max_length=32)] = "进行中"
    department: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=64)] = None
    due_on: date | None = None
    notion_url: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=500)] = None
    github_repo: OptionalShortText = None
    notes: str | None = None


class ProjectUpdate(BaseModel):
    name: Annotated[str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)] = None
    goal: str | None = None
    status: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=32)] = None
    department: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=64)] = None
    due_on: date | None = None
    notion_url: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=500)] = None
    github_repo: OptionalShortText = None
    notes: str | None = None


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    goal: str | None
    status: str
    department: str | None
    due_on: date | None
    notion_url: str | None
    github_repo: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
