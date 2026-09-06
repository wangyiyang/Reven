"""Finance entry routes."""

from decimal import Decimal, InvalidOperation
from uuid import UUID

from fastapi import APIRouter, Query, Response, status
from fastapi.responses import JSONResponse

from reven.api.dependencies import SessionDep
from reven.api.schemas.finance import (
    FinanceEntryConfirm,
    FinanceEntryCreate,
    FinanceEntryResponse,
    FinanceSummaryResponse,
)
from reven.finance.models import FinanceEntry
from reven.finance.repository import FinanceRepository

router = APIRouter(prefix="/api/finance", tags=["finance"])

_MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"


@router.get("/entries", response_model=list[FinanceEntryResponse])
async def list_entries(
    session: SessionDep,
    kind: str | None = Query(default=None, max_length=16),
    query: str | None = Query(default=None, min_length=1, max_length=200),
    status_filter: str | None = Query(default=None, alias="status", min_length=1, max_length=200),
    month: str | None = Query(default=None, pattern=_MONTH_PATTERN),
    category: str | None = Query(default=None, min_length=1, max_length=100),
) -> list[FinanceEntry]:
    statuses = [item.strip() for item in status_filter.split(",") if item.strip()] if status_filter else None
    return await FinanceRepository(session).list(
        kind=kind, query=query, statuses=statuses, month=month, category=category
    )


@router.post("/entries", response_model=FinanceEntryResponse, status_code=status.HTTP_201_CREATED)
async def create_entry(body: FinanceEntryCreate, session: SessionDep) -> FinanceEntry | JSONResponse:
    amount_cents = _to_cents(body.amount)
    if amount_cents is None:
        return _error(422, "FINANCE_AMOUNT_INVALID", "金额格式不正确")
    entry = await FinanceRepository(session).create(**_entry_values(body, amount_cents))
    await session.commit()
    return entry


@router.get("/entries/{entry_id}", response_model=FinanceEntryResponse)
async def get_entry(entry_id: UUID, session: SessionDep) -> FinanceEntry | JSONResponse:
    entry = await FinanceRepository(session).get(entry_id)
    if entry is None:
        return _error(404, "FINANCE_ENTRY_NOT_FOUND", "财务记录不存在")
    return entry


@router.put("/entries/{entry_id}", response_model=FinanceEntryResponse)
async def update_entry(entry_id: UUID, body: FinanceEntryCreate, session: SessionDep) -> FinanceEntry | JSONResponse:
    amount_cents = _to_cents(body.amount)
    if amount_cents is None:
        return _error(422, "FINANCE_AMOUNT_INVALID", "金额格式不正确")
    entry = await FinanceRepository(session).update(entry_id, **_entry_values(body, amount_cents))
    if entry is None:
        return _error(404, "FINANCE_ENTRY_NOT_FOUND", "财务记录不存在")
    await session.commit()
    return entry


@router.post("/entries/{entry_id}/confirm", response_model=FinanceEntryResponse)
async def confirm_settlement(
    entry_id: UUID, body: FinanceEntryConfirm, session: SessionDep
) -> FinanceEntry | JSONResponse:
    repository = FinanceRepository(session)
    entry = await repository.get(entry_id)
    if entry is None:
        return _error(404, "FINANCE_ENTRY_NOT_FOUND", "财务记录不存在")
    if entry.status not in ("应收", "应付"):
        return _error(409, "FINANCE_ENTRY_ALREADY_SETTLED", "该款项已确认，请勿重复操作")
    settled_status = "已收" if entry.status == "应收" else "已付"
    settled = await repository.update(entry_id, status=settled_status, occurred_on=body.occurred_on)
    if settled is None:
        return _error(404, "FINANCE_ENTRY_NOT_FOUND", "财务记录不存在")
    await session.commit()
    return settled


@router.delete("/entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_entry(entry_id: UUID, session: SessionDep) -> Response:
    deleted = await FinanceRepository(session).delete(entry_id)
    if not deleted:
        return _error(404, "FINANCE_ENTRY_NOT_FOUND", "财务记录不存在")
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/summary", response_model=FinanceSummaryResponse)
async def get_summary(
    session: SessionDep,
    month: str | None = Query(default=None, pattern=_MONTH_PATTERN),
) -> dict[str, int]:
    return await FinanceRepository(session).summary(month=month)


def _to_cents(amount: float) -> int | None:
    try:
        cents = int((Decimal(str(amount)) * 100).quantize(Decimal("1")))
    except (InvalidOperation, ValueError):
        return None
    return cents if cents > 0 else None


def _entry_values(body: FinanceEntryCreate, amount_cents: int) -> dict[str, object]:
    return {
        "kind": body.kind,
        "name": body.name,
        "amount_cents": amount_cents,
        "category": body.category,
        "occurred_on": body.occurred_on,
        "due_on": body.due_on,
        "recurrence": body.recurrence,
        "source": body.source,
        "status": body.status,
        "notes": body.notes,
    }


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"code": code, "message": message})
