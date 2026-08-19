"""Persistence access for projects."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from reven.projects.models import Project


class ProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self, status: str | None, query: str | None) -> list[Project]:
        stmt = select(Project)
        if status:
            stmt = stmt.where(Project.status == status)
        if query:
            pattern = f"%{query}%"
            stmt = stmt.where(
                (Project.name.ilike(pattern)) | (Project.goal.ilike(pattern)) | (Project.notes.ilike(pattern))
            )
        stmt = stmt.order_by(Project.due_on.is_not(None), Project.due_on, func.lower(Project.name))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get(self, project_id: UUID) -> Project | None:
        return await self.session.get(Project, project_id)

    async def create(self, **values: object) -> Project:
        project = Project(**values)
        self.session.add(project)
        await self.session.commit()
        await self.session.refresh(project)
        return project

    async def update(self, project: Project, **values: object) -> Project:
        for key, value in values.items():
            setattr(project, key, value)
        await self.session.commit()
        await self.session.refresh(project)
        return project

    async def delete(self, project: Project) -> None:
        await self.session.delete(project)
        await self.session.commit()
