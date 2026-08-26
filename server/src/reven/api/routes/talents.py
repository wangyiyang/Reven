"""Authenticated talents API routes."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, Response, status
from fastapi.responses import JSONResponse

from reven.api.dependencies import SessionDep
from reven.api.schemas.talents import (
    TalentCreate,
    TalentInteractionCreate,
    TalentInteractionResponse,
    TalentInteractionUpdate,
    TalentResponse,
    TalentUpdate,
)
from reven.scheduling import SHANGHAI
from reven.talents.models import Talent, TalentInteraction, TalentStatus
from reven.talents.repository import TalentsRepository
from reven.talents.service import InvalidRatePairError, TalentsService

router = APIRouter(prefix="/api/talents", tags=["talents"])
DueFilter = Literal["overdue", "today", "upcoming", "none"]


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"code": code, "message": message})


def _rate_pair_error() -> JSONResponse:
    return _error(422, "TALENT_RATE_PAIR_INCOMPLETE", "费率金额与单位必须同时填写或同时留空")


async def _talent(repository: TalentsRepository, talent_id: UUID) -> Talent | JSONResponse:
    talent = await repository.get_talent(talent_id)
    if talent is None:
        return _error(404, "TALENT_NOT_FOUND", "人才不存在")
    return talent


@router.get("", response_model=list[TalentResponse])
async def list_talents(
    session: SessionDep,
    talent_status: TalentStatus | None = Query(default=None, alias="status"),
    due: DueFilter | None = Query(default=None),
    q: str | None = Query(default=None, min_length=1, max_length=200),
    tag: str | None = Query(default=None, min_length=1, max_length=50),
) -> list[Talent]:
    return await TalentsRepository(session).list_talents(
        status=talent_status,
        due=due,
        query=q,
        tag=tag,
        today=datetime.now(SHANGHAI).date(),
    )


@router.post("", response_model=TalentResponse, status_code=status.HTTP_201_CREATED)
async def create_talent(payload: TalentCreate, session: SessionDep) -> Talent:
    return await TalentsService(session).create_talent(payload.model_dump())


@router.get("/{talent_id}", response_model=TalentResponse)
async def get_talent(talent_id: UUID, session: SessionDep) -> Talent | JSONResponse:
    return await _talent(TalentsRepository(session), talent_id)


@router.patch("/{talent_id}", response_model=TalentResponse)
async def update_talent(
    talent_id: UUID,
    payload: TalentUpdate,
    session: SessionDep,
) -> Talent | JSONResponse:
    talent = await _talent(TalentsRepository(session), talent_id)
    if isinstance(talent, JSONResponse):
        return talent
    try:
        return await TalentsService(session).update_talent(talent, payload.model_dump(exclude_unset=True))
    except InvalidRatePairError:
        return _rate_pair_error()


@router.delete("/{talent_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_talent(talent_id: UUID, session: SessionDep) -> Response:
    talent = await _talent(TalentsRepository(session), talent_id)
    if isinstance(talent, JSONResponse):
        return talent
    await TalentsService(session).delete_talent(talent)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{talent_id}/interactions", response_model=list[TalentInteractionResponse])
async def list_interactions(talent_id: UUID, session: SessionDep) -> list[TalentInteraction] | JSONResponse:
    repository = TalentsRepository(session)
    talent = await _talent(repository, talent_id)
    if isinstance(talent, JSONResponse):
        return talent
    return await repository.list_interactions(talent_id)


@router.post(
    "/{talent_id}/interactions",
    response_model=TalentInteractionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_interaction(
    talent_id: UUID,
    payload: TalentInteractionCreate,
    session: SessionDep,
) -> TalentInteraction | JSONResponse:
    talent = await _talent(TalentsRepository(session), talent_id)
    if isinstance(talent, JSONResponse):
        return talent
    return await TalentsService(session).create_interaction(talent, payload.model_dump())


@router.patch("/interactions/{interaction_id}", response_model=TalentInteractionResponse)
async def update_interaction(
    interaction_id: UUID,
    payload: TalentInteractionUpdate,
    session: SessionDep,
) -> TalentInteraction | JSONResponse:
    interaction = await TalentsRepository(session).get_interaction(interaction_id)
    if interaction is None:
        return _error(404, "TALENT_INTERACTION_NOT_FOUND", "跟进记录不存在")
    return await TalentsService(session).update_interaction(interaction, payload.model_dump(exclude_unset=True))


@router.delete(
    "/interactions/{interaction_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_interaction(interaction_id: UUID, session: SessionDep) -> Response:
    interaction = await TalentsRepository(session).get_interaction(interaction_id)
    if interaction is None:
        return _error(404, "TALENT_INTERACTION_NOT_FOUND", "跟进记录不存在")
    await TalentsService(session).delete_interaction(interaction)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
