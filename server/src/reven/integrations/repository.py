"""Persistence access for integrations."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from reven.integrations.models import Integration


class IntegrationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_provider(self, provider: str) -> Integration | None:
        statement = select(Integration).where(Integration.provider == provider)
        integration: Integration | None = await self.session.scalar(statement)
        return integration

    async def list_all(self) -> list[Integration]:
        statement = select(Integration).order_by(Integration.provider)
        result = await self.session.scalars(statement)
        return list(result)

    async def save(self, integration: Integration) -> Integration:
        self.session.add(integration)
        await self.session.flush()
        return integration
