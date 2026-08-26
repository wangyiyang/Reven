"""Persistence queries for talents and their follow-up interactions."""

from datetime import date
from uuid import UUID

from sqlalchemy import ScalarSelect, Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from reven.talents.models import Talent, TalentInteraction


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _earliest_due_subquery() -> ScalarSelect[date | None]:
    return (
        select(func.min(TalentInteraction.next_due_on))
        .where(TalentInteraction.talent_id == Talent.id)
        .correlate(Talent)
        .scalar_subquery()
    )


class TalentsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_talents(
        self,
        *,
        status: str | None,
        due: str | None,
        query: str | None,
        tag: str | None,
        today: date,
    ) -> list[Talent]:
        statement = select(Talent)
        if status:
            statement = statement.where(Talent.status == status)
        statement = self._filter_due(statement, due, today)
        if query:
            pattern = f"%{_escape_like(query)}%"
            statement = statement.where(
                or_(
                    Talent.name.ilike(pattern, escape="\\"),
                    Talent.organization.ilike(pattern, escape="\\"),
                )
            )
        if tag:
            statement = statement.where(Talent.tags.contains([tag]))
        statement = statement.order_by(Talent.updated_at.desc(), Talent.id)
        return list((await self.session.scalars(statement)).all())

    @staticmethod
    def _filter_due(statement: Select[tuple[Talent]], due: str | None, today: date) -> Select[tuple[Talent]]:
        if due is None:
            return statement
        earliest_due = _earliest_due_subquery()
        if due == "overdue":
            return statement.where(earliest_due < today)
        if due == "today":
            return statement.where(earliest_due == today)
        if due == "upcoming":
            return statement.where(earliest_due > today)
        return statement.where(earliest_due.is_(None))

    async def get_talent(self, talent_id: UUID) -> Talent | None:
        return await self.session.get(Talent, talent_id)

    async def add_talent(self, values: dict[str, object]) -> Talent:
        talent = Talent(**values)
        self.session.add(talent)
        await self.session.flush()
        return talent

    async def list_interactions(self, talent_id: UUID) -> list[TalentInteraction]:
        statement = (
            select(TalentInteraction)
            .where(TalentInteraction.talent_id == talent_id)
            .order_by(
                TalentInteraction.occurred_on.desc(),
                TalentInteraction.created_at.desc(),
                TalentInteraction.id.desc(),
            )
        )
        return list((await self.session.scalars(statement)).all())

    async def get_interaction(self, interaction_id: UUID) -> TalentInteraction | None:
        statement = select(TalentInteraction).where(TalentInteraction.id == interaction_id)
        result = await self.session.scalars(statement)
        return result.one_or_none()

    async def add_interaction(self, talent_id: UUID, values: dict[str, object]) -> TalentInteraction:
        interaction = TalentInteraction(talent_id=talent_id, **values)
        self.session.add(interaction)
        await self.session.flush()
        return interaction
