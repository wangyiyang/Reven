"""Public schemas for finance entries."""

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

FinanceName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
FinanceCategory = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
FinanceStatus = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)]


class FinanceEntryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["income", "expense"]
    name: FinanceName
    amount: float = Field(gt=0, le=1_000_000_000)
    category: FinanceCategory | None = None
    occurred_on: date
    due_on: date | None = None
    recurrence: str | None = Field(default=None, max_length=32)
    source: str | None = Field(default=None, max_length=100)
    status: FinanceStatus = "已记录"
    notes: str | None = None


class FinanceEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: Literal["income", "expense"]
    name: str
    amount_cents: int
    category: str | None
    occurred_on: date
    due_on: date | None
    recurrence: str | None
    source: str | None
    status: str
    notes: str | None
    created_at: datetime
    updated_at: datetime


class FinanceSummaryResponse(BaseModel):
    income_cents: int
    expense_cents: int
    net_cents: int
    receivable_cents: int
    payable_cents: int
