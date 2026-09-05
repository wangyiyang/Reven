"""SOP routes."""

from uuid import UUID

from fastapi import APIRouter, Query, Response, status
from fastapi.responses import JSONResponse

from reven.api.dependencies import SessionDep
from reven.api.schemas.sops import SopCreate, SopResponse, SopUpdate
from reven.sops.models import Sop
from reven.sops.repository import SopRepository

router = APIRouter(prefix="/api/sops", tags=["sops"])


def not_found(detail: str = "SOP 不存在") -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": detail})


@router.get("", response_model=list[SopResponse])
async def list_sops(
    session: SessionDep,
    kind: str | None = Query(default=None, max_length=32),
    sop_status: str | None = Query(default=None, alias="status", max_length=32),
    query: str | None = Query(default=None, min_length=1, max_length=200),
) -> list[Sop]:
    return await SopRepository(session).list(kind, sop_status, query)


@router.post("", response_model=SopResponse, status_code=status.HTTP_201_CREATED)
async def create_sop(payload: SopCreate, session: SessionDep) -> Sop:
    return await SopRepository(session).create(**payload.model_dump())


@router.get("/{sop_id}", response_model=SopResponse)
async def get_sop(sop_id: UUID, session: SessionDep) -> Sop | JSONResponse:
    sop = await SopRepository(session).get(sop_id)
    if sop is None:
        return not_found()
    return sop


@router.put("/{sop_id}", response_model=SopResponse)
async def update_sop(sop_id: UUID, payload: SopUpdate, session: SessionDep) -> Sop | JSONResponse:
    repository = SopRepository(session)
    sop = await repository.get(sop_id)
    if sop is None:
        return not_found()
    values = payload.model_dump(exclude_unset=True)
    if not values:
        return sop
    return await repository.update(sop, **values)


@router.delete("/{sop_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_sop(sop_id: UUID, session: SessionDep) -> Response:
    repository = SopRepository(session)
    sop = await repository.get(sop_id)
    if sop is None:
        return not_found()
    await repository.delete(sop)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
