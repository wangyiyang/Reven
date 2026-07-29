"""Article index operations used by API commands."""

from uuid import UUID

from reven.articles.models import Article
from reven.articles.repository import ArticleRepository


class ArticleService:
    def __init__(self, repository: ArticleRepository) -> None:
        self.repository = repository

    async def get(self, article_id: UUID) -> Article | None:
        return await self.repository.get_by_id(article_id)
