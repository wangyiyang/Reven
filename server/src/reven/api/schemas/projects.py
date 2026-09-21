"""Public schemas for projects."""

import re
from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
OptionalShortText = Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=200)]

_GITHUB_REPO_RE = re.compile(r"^(?:https://github\.com/)?[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?/?$")


def _validate_github_repo(value: str | None) -> str | None:
    if value is None:
        return None
    if not _GITHUB_REPO_RE.fullmatch(value):
        raise ValueError("GitHub 仓库需为 owner/repo 或 GitHub URL")
    return value


class ProjectCreate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    goal: str | None = None
    status: Annotated[str, StringConstraints(strip_whitespace=True, max_length=32)] = "进行中"
    department: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=64)] = None
    due_on: date | None = None
    github_repo: OptionalShortText = None
    notes: str | None = None

    _github_repo = field_validator("github_repo")(_validate_github_repo)


class ProjectUpdate(BaseModel):
    name: Annotated[str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)] = None
    goal: str | None = None
    status: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=32)] = None
    department: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=64)] = None
    due_on: date | None = None
    github_repo: OptionalShortText = None
    notes: str | None = None

    _github_repo = field_validator("github_repo")(_validate_github_repo)


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    goal: str | None
    status: str
    department: str | None
    due_on: date | None
    github_repo: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
