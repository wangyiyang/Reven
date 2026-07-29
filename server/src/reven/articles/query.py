"""Read-only article and publication-job queries."""

from uuid import UUID

from sqlalchemy import Select, func, nullslast, select
from sqlalchemy.ext.asyncio import AsyncSession

from reven.articles.models import Article
from reven.jobs.models import PublicationJob

ARTICLE_DETAIL_JOB_LIMIT = 50


class ArticleQuery:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_articles(
        self,
        *,
        page: int,
        page_size: int,
        status: str | None,
        channel: str | None,
        query: str | None,
    ) -> tuple[list[Article], int]:
        statement = self._filters(status=status, channel=channel, query=query)
        total = await self.session.scalar(select(func.count()).select_from(statement.subquery()))
        ordered = statement.order_by(
            nullslast(Article.planned_at.asc()),
            Article.notion_last_edited_at.desc(),
            Article.id,
        )
        items = list(await self.session.scalars(ordered.offset((page - 1) * page_size).limit(page_size)))
        return items, int(total or 0)

    def _filters(self, *, status: str | None, channel: str | None, query: str | None) -> Select[tuple[Article]]:
        statement = select(Article)
        if status:
            statement = statement.where(
                (Article.notion_status == status) | (Article.automation_status == status)
            )
        if channel:
            statement = statement.where(Article.target_channels.contains([channel]))
        if query:
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            statement = statement.where(Article.title.ilike(f"%{escaped}%", escape="\\"))
        return statement

    async def get(self, article_id: UUID) -> Article | None:
        return await self.session.get(Article, article_id)

    async def jobs(self, article_id: UUID) -> tuple[list[PublicationJob], int]:
        total = await self.session.scalar(
            select(func.count(PublicationJob.id)).where(PublicationJob.article_id == article_id)
        )
        statement = (
            select(PublicationJob)
            .where(PublicationJob.article_id == article_id)
            .order_by(PublicationJob.created_at.desc(), PublicationJob.id)
            .limit(ARTICLE_DETAIL_JOB_LIMIT)
        )
        return list(await self.session.scalars(statement)), int(total or 0)

    async def job(self, article_id: UUID, job_id: UUID) -> PublicationJob | None:
        statement = select(PublicationJob).where(
            PublicationJob.id == job_id,
            PublicationJob.article_id == article_id,
        )
        job: PublicationJob | None = await self.session.scalar(statement)
        return job
