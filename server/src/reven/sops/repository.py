"""Persistence access for SOP entries."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from reven.sops.models import Sop


class SopRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self, kind: str | None, status: str | None, query: str | None) -> list[Sop]:
        stmt = select(Sop)
        if kind:
            stmt = stmt.where(Sop.kind == kind)
        if status:
            stmt = stmt.where(Sop.status == status)
        if query:
            pattern = f"%{query}%"
            stmt = stmt.where((Sop.title.ilike(pattern)) | (Sop.body.ilike(pattern)))
        stmt = stmt.order_by(Sop.updated_at.desc(), func.lower(Sop.title))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get(self, sop_id: UUID) -> Sop | None:
        return await self.session.get(Sop, sop_id)

    async def create(self, **values: object) -> Sop:
        sop = Sop(**values)
        self.session.add(sop)
        await self.session.commit()
        await self.session.refresh(sop)
        return sop

    async def update(self, sop: Sop, **values: object) -> Sop:
        for key, value in values.items():
            setattr(sop, key, value)
        await self.session.commit()
        await self.session.refresh(sop)
        return sop

    async def delete(self, sop: Sop) -> None:
        await self.session.delete(sop)
        await self.session.commit()
