"""Transactional talents mutations and business invariants."""

from sqlalchemy.ext.asyncio import AsyncSession

from reven.scheduling import utc_now
from reven.talents.models import Talent, TalentInteraction
from reven.talents.repository import TalentsRepository


class InvalidRatePairError(ValueError):
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

    async def _commit_and_refresh(self, model: Talent | TalentInteraction) -> None:
        await self.session.commit()
        await self.session.refresh(model)


def _assign(model: Talent | TalentInteraction, values: dict[str, object]) -> None:
    for key, value in values.items():
        setattr(model, key, value)
