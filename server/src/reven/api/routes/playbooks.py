"""Playbook routes."""

from uuid import UUID

from fastapi import APIRouter, Query, Response, status
from fastapi.responses import JSONResponse

from reven.api.dependencies import SessionDep
from reven.api.schemas.playbooks import PlaybookCreate, PlaybookResponse, PlaybookUpdate
from reven.playbooks.models import Playbook
from reven.playbooks.repository import PlaybookRepository

router = APIRouter(prefix="/api/playbooks", tags=["playbooks"])


def not_found(detail: str = "Playbook 不存在") -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": detail})


@router.get("", response_model=list[PlaybookResponse])
async def list_playbooks(
    session: SessionDep,
    kind: str | None = Query(default=None, max_length=32),
    playbook_status: str | None = Query(default=None, alias="status", max_length=32),
    query: str | None = Query(default=None, min_length=1, max_length=200),
) -> list[Playbook]:
    return await PlaybookRepository(session).list(kind, playbook_status, query)


@router.post("", response_model=PlaybookResponse, status_code=status.HTTP_201_CREATED)
async def create_playbook(payload: PlaybookCreate, session: SessionDep) -> Playbook:
    return await PlaybookRepository(session).create(**payload.model_dump())


@router.get("/{playbook_id}", response_model=PlaybookResponse)
async def get_playbook(playbook_id: UUID, session: SessionDep) -> Playbook | JSONResponse:
    playbook = await PlaybookRepository(session).get(playbook_id)
    if playbook is None:
        return not_found()
    return playbook


@router.put("/{playbook_id}", response_model=PlaybookResponse)
async def update_playbook(playbook_id: UUID, payload: PlaybookUpdate, session: SessionDep) -> Playbook | JSONResponse:
    repository = PlaybookRepository(session)
    playbook = await repository.get(playbook_id)
    if playbook is None:
        return not_found()
    values = payload.model_dump(exclude_unset=True)
    if not values:
        return playbook
    return await repository.update(playbook, **values)


@router.delete("/{playbook_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_playbook(playbook_id: UUID, session: SessionDep) -> Response:
    repository = PlaybookRepository(session)
    playbook = await repository.get(playbook_id)
    if playbook is None:
        return not_found()
    await repository.delete(playbook)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
