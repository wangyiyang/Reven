"""Explicit tool sessions and structured business receipts."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class _BusinessEntity(Protocol):
    __tablename__: str
    id: UUID


class ToolSessionBinding:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        session: AsyncSession | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._bound_session = session
        self.receipt: dict[str, object] = {"records": []}

    @property
    def _commits(self) -> bool:
        return self._bound_session is None

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[AsyncSession]:
        if self._bound_session is not None:
            yield self._bound_session
        else:
            async with self._session_factory() as session:
                yield session

    async def _commit(self, session: AsyncSession) -> None:
        if self._commits:
            await session.commit()
        else:
            await session.flush()

    def _record_entity(self, entity: _BusinessEntity) -> None:
        self._record_id(entity.__tablename__, entity.id)

    def _record_id(self, table: str, entity_id: UUID) -> None:
        records = self.receipt["records"]
        assert isinstance(records, list)
        records.append({"table": table, "id": str(entity_id)})
