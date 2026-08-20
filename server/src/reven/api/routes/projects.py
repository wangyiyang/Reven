"""Project routes."""

from uuid import UUID

from fastapi import APIRouter, Query, Response, status
from fastapi.responses import JSONResponse

from reven.api.dependencies import SessionDep
from reven.api.schemas.projects import ProjectCreate, ProjectResponse, ProjectUpdate
from reven.projects.models import Project
from reven.projects.repository import ProjectRepository

router = APIRouter(prefix="/api/projects", tags=["projects"])


def not_found(detail: str = "项目不存在") -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": detail})


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    session: SessionDep,
    status_filter: str | None = Query(default=None, alias="status"),
    query: str | None = Query(default=None),
) -> list[Project]:
    return await ProjectRepository(session).list(status_filter, query)


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(payload: ProjectCreate, session: SessionDep) -> Project:
    return await ProjectRepository(session).create(**payload.model_dump())


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(project_id: UUID, payload: ProjectUpdate, session: SessionDep) -> Project | JSONResponse:
    repository = ProjectRepository(session)
    project = await repository.get(project_id)
    if project is None:
        return not_found()
    values = payload.model_dump(exclude_unset=True)
    if not values:
        return project
    return await repository.update(project, **values)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_project(project_id: UUID, session: SessionDep) -> Response:
    repository = ProjectRepository(session)
    project = await repository.get(project_id)
    if project is None:
        return not_found()
    await repository.delete(project)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
