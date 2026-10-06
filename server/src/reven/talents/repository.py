"""Persistence queries for talents and their follow-up interactions."""

from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import ScalarSelect, Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from reven.talents.models import Talent, TalentEducation, TalentExperience, TalentInteraction


@dataclass(frozen=True)
class TalentPlan:
    """人才与其派生当前计划：最新一条互动记录（occurred_on/created_at/id 倒序）的下一步行动与到期日。"""

    talent: Talent
    next_action: str | None
    next_due_on: date | None


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _latest_action_subquery() -> ScalarSelect[str | None]:
    return (
        select(TalentInteraction.next_action)
        .where(TalentInteraction.talent_id == Talent.id)
        .order_by(
            TalentInteraction.occurred_on.desc(),
            TalentInteraction.created_at.desc(),
            TalentInteraction.id.desc(),
        )
        .limit(1)
        .correlate(Talent)
        .scalar_subquery()
    )


def _latest_due_subquery() -> ScalarSelect[date | None]:
    return (
        select(TalentInteraction.next_due_on)
        .where(TalentInteraction.talent_id == Talent.id)
        .order_by(
            TalentInteraction.occurred_on.desc(),
            TalentInteraction.created_at.desc(),
            TalentInteraction.id.desc(),
        )
        .limit(1)
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
        statement = self._filtered(select(Talent), status=status, due=due, query=query, tag=tag, today=today)
        return list((await self.session.scalars(statement)).all())

    async def list_talent_plans(
        self,
        *,
        status: str | None,
        due: str | None,
        query: str | None,
        tag: str | None,
        today: date,
    ) -> list[TalentPlan]:
        """与 list_talents 同筛选同排序，但随行带出派生当前计划（供 MCP 列表行展示）。"""
        statement = self._filtered(
            select(Talent, _latest_action_subquery(), _latest_due_subquery()),
            status=status,
            due=due,
            query=query,
            tag=tag,
            today=today,
        )
        rows = (await self.session.execute(statement)).all()
        return [TalentPlan(talent=row[0], next_action=row[1], next_due_on=row[2]) for row in rows]

    async def get_talent_plan(self, talent_id: UUID) -> TalentPlan | None:
        """单个人才 + 派生当前计划；人才不存在返回 None。"""
        statement = select(Talent, _latest_action_subquery(), _latest_due_subquery()).where(Talent.id == talent_id)
        row = (await self.session.execute(statement)).one_or_none()
        if row is None:
            return None
        return TalentPlan(talent=row[0], next_action=row[1], next_due_on=row[2])

    async def find_talents_by_name(self, name: str) -> list[Talent]:
        """按姓名精确匹配（ talent_import_profile 的同名判定用；重名返回多个）。"""
        statement = select(Talent).where(Talent.name == name).order_by(Talent.created_at, Talent.id)
        return list((await self.session.scalars(statement)).all())

    def _filtered(
        self,
        statement: Select[Any],
        *,
        status: str | None,
        due: str | None,
        query: str | None,
        tag: str | None,
        today: date,
    ) -> Select[Any]:
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
        return statement.order_by(Talent.updated_at.desc(), Talent.id)

    @staticmethod
    def _filter_due(statement: Select[Any], due: str | None, today: date) -> Select[Any]:
        if due is None:
            return statement
        latest_due = _latest_due_subquery()
        if due == "overdue":
            return statement.where(latest_due < today)
        if due == "today":
            return statement.where(latest_due == today)
        if due == "upcoming":
            return statement.where(latest_due > today)
        return statement.where(latest_due.is_(None))

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

    async def list_experiences(self, talent_id: UUID) -> list[TalentExperience]:
        statement = (
            select(TalentExperience)
            .where(TalentExperience.talent_id == talent_id)
            .order_by(
                TalentExperience.end_on.is_(None).desc(),
                TalentExperience.start_on.desc(),
                TalentExperience.created_at.desc(),
            )
        )
        return list((await self.session.scalars(statement)).all())

    async def get_experience(self, talent_id: UUID, experience_id: UUID) -> TalentExperience | None:
        statement = select(TalentExperience).where(
            TalentExperience.id == experience_id,
            TalentExperience.talent_id == talent_id,
        )
        result = await self.session.scalars(statement)
        return result.one_or_none()

    async def add_experience(self, talent_id: UUID, values: dict[str, object]) -> TalentExperience:
        experience = TalentExperience(talent_id=talent_id, **values)
        self.session.add(experience)
        await self.session.flush()
        return experience

    async def list_educations(self, talent_id: UUID) -> list[TalentEducation]:
        statement = (
            select(TalentEducation)
            .where(TalentEducation.talent_id == talent_id)
            .order_by(
                TalentEducation.end_on.is_(None).desc(),
                TalentEducation.start_on.desc(),
                TalentEducation.created_at.desc(),
            )
        )
        return list((await self.session.scalars(statement)).all())

    async def get_education(self, talent_id: UUID, education_id: UUID) -> TalentEducation | None:
        statement = select(TalentEducation).where(
            TalentEducation.id == education_id,
            TalentEducation.talent_id == talent_id,
        )
        result = await self.session.scalars(statement)
        return result.one_or_none()

    async def add_education(self, talent_id: UUID, values: dict[str, object]) -> TalentEducation:
        education = TalentEducation(talent_id=talent_id, **values)
        self.session.add(education)
        await self.session.flush()
        return education
