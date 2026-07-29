"""Persistence access for articles."""

from dataclasses import asdict
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from reven.articles.models import Article
from reven.domain import parse_target_channels
from reven.integrations.notion.models import MappedNotionPage
from reven.scheduling import resolve_scheduled_at, utc_now


class ArticleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_notion_page_id(self, page_id: str) -> Article | None:
        statement = select(Article).where(Article.notion_page_id == page_id)
        article: Article | None = await self.session.scalar(statement)
        return article

    async def get_by_id(self, article_id: UUID) -> Article | None:
        article: Article | None = await self.session.get(Article, article_id)
        return article

    async def upsert_from_notion(self, page: MappedNotionPage) -> Article:
        article = await self.get_by_notion_page_id(page.page_id)
        if article is None:
            article = Article(notion_page_id=page.page_id)
            self.session.add(article)
        article.notion_url = page.url
        article.title = page.title
        article.notion_status = page.status
        article.target_channels = page.target_channels
        article.planned_at = resolve_scheduled_at(page.planned_raw) if page.planned_raw else None
        article.cover_metadata = _cover_metadata(page)
        article.notion_metadata = {
            "categories": page.categories,
            "summary": page.summary,
            "target_channels_used_default": parse_target_channels(page.target_channels).used_default,
        }
        article.notion_last_edited_at = page.last_edited_at
        article.last_synced_at = utc_now()
        await self.session.flush()
        return article


def _cover_metadata(page: MappedNotionPage) -> dict[str, object]:
    if page.cover is None:
        return {}
    metadata: dict[str, object] = asdict(page.cover)
    expiry_time = metadata.get("expiry_time")
    if isinstance(expiry_time, datetime):
        metadata["expiry_time"] = expiry_time.isoformat()
    return metadata
