"""Persistence access for integrations."""

from sqlalchemy.ext.asyncio import AsyncSession


class IntegrationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
