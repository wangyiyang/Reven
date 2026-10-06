"""Transactional talents mutations and business invariants."""

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from reven.scheduling import utc_now
from reven.talents.models import Talent, TalentEducation, TalentExperience, TalentInteraction
from reven.talents.repository import TalentsRepository

TalentModel = Talent | TalentInteraction | TalentExperience | TalentEducation


class InvalidRatePairError(ValueError):
    pass


class InvalidDateRangeError(ValueError):
    pass


class TalentsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = TalentsRepository(session)

    async def create_talent(self, values: dict[str, object]) -> Talent:
        talent = await self.repository.add_talent(values)
        await self._commit_and_refresh(talent)
        return talent

    async def update_talent(self, talent: Talent, values: dict[str, object]) -> Talent:
        amount = values.get("rate_amount", talent.rate_amount)
        unit = values.get("rate_unit", talent.rate_unit)
        if (amount is None) != (unit is None):
            raise InvalidRatePairError
        _assign(talent, values)
        await self._commit_and_refresh(talent)
        return talent

    async def delete_talent(self, talent: Talent) -> None:
        await self.session.delete(talent)
        await self.session.commit()

    async def create_interaction(self, talent: Talent, values: dict[str, object]) -> TalentInteraction:
        interaction = await self.repository.add_interaction(talent.id, values)
        talent.updated_at = utc_now()
        await self._commit_and_refresh(interaction)
        return interaction

    async def update_interaction(
        self,
        interaction: TalentInteraction,
        values: dict[str, object],
    ) -> TalentInteraction:
        _assign(interaction, values)
        await self._commit_and_refresh(interaction)
        return interaction

    async def delete_interaction(self, interaction: TalentInteraction) -> None:
        talent = await self.repository.get_talent(interaction.talent_id)
        if talent is not None:
            talent.updated_at = utc_now()
        await self.session.delete(interaction)
        await self.session.commit()

    # 履历/院校修订不等于接洽活跃：写操作均不 bump talent.updated_at（与 CRM 一致）。

    async def create_experience(self, talent: Talent, values: dict[str, object]) -> TalentExperience:
        experience = await self.repository.add_experience(talent.id, values)
        await self._commit_and_refresh(experience)
        return experience

    async def update_experience(
        self,
        experience: TalentExperience,
        values: dict[str, object],
    ) -> TalentExperience:
        _validate_date_range(experience.start_on, experience.end_on, values)
        _assign(experience, values)
        await self._commit_and_refresh(experience)
        return experience

    async def delete_experience(self, experience: TalentExperience) -> None:
        await self.session.delete(experience)
        await self.session.commit()

    async def create_education(self, talent: Talent, values: dict[str, object]) -> TalentEducation:
        education = await self.repository.add_education(talent.id, values)
        await self._commit_and_refresh(education)
        return education

    async def update_education(
        self,
        education: TalentEducation,
        values: dict[str, object],
    ) -> TalentEducation:
        _validate_date_range(education.start_on, education.end_on, values)
        _assign(education, values)
        await self._commit_and_refresh(education)
        return education

    async def delete_education(self, education: TalentEducation) -> None:
        await self.session.delete(education)
        await self.session.commit()

    async def _commit_and_refresh(self, model: TalentModel) -> None:
        await self.session.commit()
        await self.session.refresh(model)


def _assign(model: TalentModel, values: dict[str, object]) -> None:
    for key, value in values.items():
        setattr(model, key, value)


def _validate_date_range(current_start: date, current_end: date | None, values: dict[str, object]) -> None:
    """PATCH 合并语义：未提交字段取现值后校验最终区间（单边提交只能在 service 判）。"""
    start = values.get("start_on", current_start)
    end = values.get("end_on", current_end)
    if isinstance(start, date) and isinstance(end, date) and end < start:
        raise InvalidDateRangeError
