"""Persistence access for playbooks."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from reven.playbooks.models import Playbook


class PlaybookRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self, kind: str | None, status: str | None, query: str | None) -> list[Playbook]:
        stmt = select(Playbook)
        if kind:
            stmt = stmt.where(Playbook.kind == kind)
        if status:
            stmt = stmt.where(Playbook.status == status)
        if query:
            pattern = f"%{query}%"
            stmt = stmt.where((Playbook.title.ilike(pattern)) | (Playbook.body.ilike(pattern)))
        stmt = stmt.order_by(Playbook.updated_at.desc(), func.lower(Playbook.title))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get(self, playbook_id: UUID) -> Playbook | None:
        return await self.session.get(Playbook, playbook_id)

    async def create(self, **values: object) -> Playbook:
        playbook = Playbook(**values)
        self.session.add(playbook)
        await self.session.commit()
        await self.session.refresh(playbook)
        return playbook

    async def update(self, playbook: Playbook, **values: object) -> Playbook:
        for key, value in values.items():
            setattr(playbook, key, value)
        await self.session.commit()
        await self.session.refresh(playbook)
        return playbook

    async def delete(self, playbook: Playbook) -> None:
        await self.session.delete(playbook)
        await self.session.commit()
