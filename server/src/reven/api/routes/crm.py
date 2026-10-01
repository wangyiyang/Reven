"""Authenticated CRM API routes."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, Response, status
from fastapi.responses import JSONResponse

from reven.api.dependencies import SessionDep
from reven.api.schemas.crm import (
    ContactCreate,
    ContactResponse,
    ContactUpdate,
    CustomerCreate,
    CustomerResponse,
    CustomerUpdate,
    FollowUpCreate,
    FollowUpResponse,
    FollowUpUpdate,
)
from reven.crm.errors import ContactNotFoundError, CustomerNotFoundError, FollowUpNotFoundError, InvalidActionPairError
from reven.crm.models import Contact, Customer, CustomerStatus, FollowUp
from reven.crm.repository import CrmRepository
from reven.crm.service import CrmService
from reven.scheduling import SHANGHAI

router = APIRouter(prefix="/api/crm", tags=["crm"])
DueFilter = Literal["overdue", "today", "upcoming", "none"]


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"code": code, "message": message})


def _mutation_error(
    error: CustomerNotFoundError | ContactNotFoundError | FollowUpNotFoundError | InvalidActionPairError,
) -> JSONResponse:
    if isinstance(error, CustomerNotFoundError):
        return _error(404, "CRM_CUSTOMER_NOT_FOUND", "客户不存在")
    if isinstance(error, ContactNotFoundError):
        return _error(404, "CRM_CONTACT_NOT_FOUND", "联系人不存在")
    if isinstance(error, FollowUpNotFoundError):
        return _error(404, "CRM_FOLLOW_UP_NOT_FOUND", "跟进记录不存在")
    return _error(422, "CRM_NEXT_ACTION_REQUIRED", "设置跟进日期时必须提供下一步行动")


async def _customer(repository: CrmRepository, customer_id: UUID) -> Customer | JSONResponse:
    customer = await repository.get_customer(customer_id)
    if customer is None:
        return _error(404, "CRM_CUSTOMER_NOT_FOUND", "客户不存在")
    return customer


@router.get("/customers", response_model=list[CustomerResponse])
async def list_customers(
    session: SessionDep,
    customer_status: CustomerStatus | None = Query(default=None, alias="status"),
    due: DueFilter | None = Query(default=None),
    query: str | None = Query(default=None, min_length=1, max_length=200),
) -> list[Customer]:
    return await CrmRepository(session).list_customers(
        status=customer_status,
        due=due,
        query=query,
        today=datetime.now(SHANGHAI).date(),
    )


@router.post("/customers", response_model=CustomerResponse, status_code=status.HTTP_201_CREATED)
async def create_customer(payload: CustomerCreate, session: SessionDep) -> Customer:
    return await CrmService(session).create_customer(payload)


@router.get("/customers/{customer_id}", response_model=CustomerResponse)
async def get_customer(customer_id: UUID, session: SessionDep) -> Customer | JSONResponse:
    return await _customer(CrmRepository(session), customer_id)


@router.put("/customers/{customer_id}", response_model=CustomerResponse)
async def update_customer(
    customer_id: UUID,
    payload: CustomerUpdate,
    session: SessionDep,
) -> Customer | JSONResponse:
    try:
        return await CrmService(session).update_customer(customer_id, payload)
    except (CustomerNotFoundError, InvalidActionPairError) as exc:
        return _mutation_error(exc)


@router.delete("/customers/{customer_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_customer(customer_id: UUID, session: SessionDep) -> Response:
    try:
        await CrmService(session).delete_customer(customer_id)
    except CustomerNotFoundError as exc:
        return _mutation_error(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/customers/{customer_id}/contacts", response_model=list[ContactResponse])
async def list_contacts(customer_id: UUID, session: SessionDep) -> list[Contact] | JSONResponse:
    repository = CrmRepository(session)
    customer = await _customer(repository, customer_id)
    if isinstance(customer, JSONResponse):
        return customer
    return await repository.list_contacts(customer_id)


@router.post(
    "/customers/{customer_id}/contacts",
    response_model=ContactResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_contact(
    customer_id: UUID,
    payload: ContactCreate,
    session: SessionDep,
) -> Contact | JSONResponse:
    try:
        _, contact = await CrmService(session).create_contact(customer_id, payload)
        return contact
    except CustomerNotFoundError as exc:
        return _mutation_error(exc)


@router.put("/customers/{customer_id}/contacts/{contact_id}", response_model=ContactResponse)
async def update_contact(
    customer_id: UUID,
    contact_id: UUID,
    payload: ContactUpdate,
    session: SessionDep,
) -> Contact | JSONResponse:
    try:
        return await CrmService(session).update_contact(customer_id, contact_id, payload)
    except ContactNotFoundError as exc:
        return _mutation_error(exc)


@router.delete(
    "/customers/{customer_id}/contacts/{contact_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_contact(customer_id: UUID, contact_id: UUID, session: SessionDep) -> Response:
    try:
        await CrmService(session).delete_contact(customer_id, contact_id)
    except ContactNotFoundError as exc:
        return _mutation_error(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/customers/{customer_id}/follow-ups", response_model=list[FollowUpResponse])
async def list_follow_ups(customer_id: UUID, session: SessionDep) -> list[FollowUp] | JSONResponse:
    repository = CrmRepository(session)
    customer = await _customer(repository, customer_id)
    if isinstance(customer, JSONResponse):
        return customer
    return await repository.list_follow_ups(customer_id)


@router.post(
    "/customers/{customer_id}/follow-ups",
    response_model=FollowUpResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_follow_up(
    customer_id: UUID,
    payload: FollowUpCreate,
    session: SessionDep,
) -> FollowUp | JSONResponse:
    try:
        _, follow_up = await CrmService(session).create_follow_up(customer_id, payload)
        return follow_up
    except (CustomerNotFoundError, ContactNotFoundError) as exc:
        return _mutation_error(exc)


@router.put("/customers/{customer_id}/follow-ups/{follow_up_id}", response_model=FollowUpResponse)
async def update_follow_up(
    customer_id: UUID,
    follow_up_id: UUID,
    payload: FollowUpUpdate,
    session: SessionDep,
) -> FollowUp | JSONResponse:
    try:
        return await CrmService(session).update_follow_up(customer_id, follow_up_id, payload)
    except (FollowUpNotFoundError, ContactNotFoundError, InvalidActionPairError) as exc:
        return _mutation_error(exc)


@router.delete(
    "/customers/{customer_id}/follow-ups/{follow_up_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_follow_up(customer_id: UUID, follow_up_id: UUID, session: SessionDep) -> Response:
    try:
        await CrmService(session).delete_follow_up(customer_id, follow_up_id)
    except FollowUpNotFoundError as exc:
        return _mutation_error(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
