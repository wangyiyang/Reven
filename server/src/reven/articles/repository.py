"""Persistence access for articles."""

from sqlalchemy.ext.asyncio import AsyncSession


class ArticleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
