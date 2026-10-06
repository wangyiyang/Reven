"""Authenticated talents API routes."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, Response, status
from fastapi.responses import JSONResponse

from reven.api.dependencies import SessionDep
from reven.api.schemas.talents import (
    TalentCreate,
    TalentEducationCreate,
    TalentEducationResponse,
    TalentEducationUpdate,
    TalentExperienceCreate,
    TalentExperienceResponse,
    TalentExperienceUpdate,
    TalentInteractionCreate,
    TalentInteractionResponse,
    TalentInteractionUpdate,
    TalentResponse,
    TalentUpdate,
)
from reven.scheduling import SHANGHAI
from reven.talents.errors import InvalidDateRangeError, InvalidRatePairError
from reven.talents.models import Talent, TalentEducation, TalentExperience, TalentInteraction, TalentStatus
from reven.talents.repository import TalentsRepository
from reven.talents.service import TalentsService

router = APIRouter(prefix="/api/talents", tags=["talents"])
DueFilter = Literal["overdue", "today", "upcoming", "none"]


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"code": code, "message": message})


def _rate_pair_error() -> JSONResponse:
    return _error(422, "TALENT_RATE_PAIR_INCOMPLETE", "费率金额与单位必须同时填写或同时留空")


def _date_range_error() -> JSONResponse:
    return _error(422, "TALENT_DATE_RANGE_INVALID", "结束日期不能早于开始日期")


async def _talent(repository: TalentsRepository, talent_id: UUID) -> Talent | JSONResponse:
    talent = await repository.get_talent(talent_id)
    if talent is None:
        return _error(404, "TALENT_NOT_FOUND", "人才不存在")
    return talent


async def _experience(
    repository: TalentsRepository,
    talent_id: UUID,
    experience_id: UUID,
) -> TalentExperience | JSONResponse:
    experience = await repository.get_experience(talent_id, experience_id)
    if experience is None:
        return _error(404, "TALENT_EXPERIENCE_NOT_FOUND", "履历不存在")
    return experience


async def _education(
    repository: TalentsRepository,
    talent_id: UUID,
    education_id: UUID,
) -> TalentEducation | JSONResponse:
    education = await repository.get_education(talent_id, education_id)
    if education is None:
        return _error(404, "TALENT_EDUCATION_NOT_FOUND", "院校经历不存在")
    return education


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


@router.get("/{talent_id}/experiences", response_model=list[TalentExperienceResponse])
async def list_experiences(talent_id: UUID, session: SessionDep) -> list[TalentExperience] | JSONResponse:
    repository = TalentsRepository(session)
    talent = await _talent(repository, talent_id)
    if isinstance(talent, JSONResponse):
        return talent
    return await repository.list_experiences(talent_id)


@router.post(
    "/{talent_id}/experiences",
    response_model=TalentExperienceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_experience(
    talent_id: UUID,
    payload: TalentExperienceCreate,
    session: SessionDep,
) -> TalentExperience | JSONResponse:
    talent = await _talent(TalentsRepository(session), talent_id)
    if isinstance(talent, JSONResponse):
        return talent
    return await TalentsService(session).create_experience(talent, payload.model_dump())


@router.put("/{talent_id}/experiences/{experience_id}", response_model=TalentExperienceResponse)
async def update_experience(
    talent_id: UUID,
    experience_id: UUID,
    payload: TalentExperienceUpdate,
    session: SessionDep,
) -> TalentExperience | JSONResponse:
    experience = await _experience(TalentsRepository(session), talent_id, experience_id)
    if isinstance(experience, JSONResponse):
        return experience
    try:
        return await TalentsService(session).update_experience(experience, payload.model_dump(exclude_unset=True))
    except InvalidDateRangeError:
        return _date_range_error()


@router.delete(
    "/{talent_id}/experiences/{experience_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_experience(talent_id: UUID, experience_id: UUID, session: SessionDep) -> Response:
    experience = await _experience(TalentsRepository(session), talent_id, experience_id)
    if isinstance(experience, JSONResponse):
        return experience
    await TalentsService(session).delete_experience(experience)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{talent_id}/educations", response_model=list[TalentEducationResponse])
async def list_educations(talent_id: UUID, session: SessionDep) -> list[TalentEducation] | JSONResponse:
    repository = TalentsRepository(session)
    talent = await _talent(repository, talent_id)
    if isinstance(talent, JSONResponse):
        return talent
    return await repository.list_educations(talent_id)


@router.post(
    "/{talent_id}/educations",
    response_model=TalentEducationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_education(
    talent_id: UUID,
    payload: TalentEducationCreate,
    session: SessionDep,
) -> TalentEducation | JSONResponse:
    talent = await _talent(TalentsRepository(session), talent_id)
    if isinstance(talent, JSONResponse):
        return talent
    return await TalentsService(session).create_education(talent, payload.model_dump())


@router.put("/{talent_id}/educations/{education_id}", response_model=TalentEducationResponse)
async def update_education(
    talent_id: UUID,
    education_id: UUID,
    payload: TalentEducationUpdate,
    session: SessionDep,
) -> TalentEducation | JSONResponse:
    education = await _education(TalentsRepository(session), talent_id, education_id)
    if isinstance(education, JSONResponse):
        return education
    try:
        return await TalentsService(session).update_education(education, payload.model_dump(exclude_unset=True))
    except InvalidDateRangeError:
        return _date_range_error()


@router.delete(
    "/{talent_id}/educations/{education_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_education(talent_id: UUID, education_id: UUID, session: SessionDep) -> Response:
    education = await _education(TalentsRepository(session), talent_id, education_id)
    if isinstance(education, JSONResponse):
        return education
    await TalentsService(session).delete_education(education)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
