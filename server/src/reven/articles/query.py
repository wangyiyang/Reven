"""Read-only article and publication-job queries."""

from uuid import UUID

from sqlalchemy import Select, func, literal, nullslast, or_, select, union_all
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
            statement = statement.where((Article.notion_status == status) | (Article.automation_status == status))
        if channel:
            statement = statement.where(or_(Article.target_channels.contains([channel]), Article.target_channels == []))
        if query:
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            statement = statement.where(Article.title.ilike(f"%{escaped}%", escape="\\"))
        return statement

    async def get(self, article_id: UUID) -> Article | None:
        return await self.session.get(Article, article_id)

    async def latest_channel_jobs(self, article_ids: list[UUID]) -> dict[tuple[UUID, str], PublicationJob]:
        if not article_ids:
            return {}
        ranked = union_all(
            self._ranked_channel_jobs(article_ids, "个人博客"),
            self._ranked_channel_jobs(article_ids, "微信公众号"),
        ).subquery()
        statement = (
            select(PublicationJob, ranked.c.channel)
            .join(ranked, ranked.c.job_id == PublicationJob.id)
            .where(ranked.c.position == 1)
        )
        rows = await self.session.execute(statement)
        return {(job.article_id, channel): job for job, channel in rows}

    def _ranked_channel_jobs(
        self,
        article_ids: list[UUID],
        channel: str,
    ) -> Select[tuple[UUID, str, int]]:
        return select(
            PublicationJob.id.label("job_id"),
            literal(channel).label("channel"),
            func.row_number()
            .over(
                partition_by=PublicationJob.article_id,
                order_by=(PublicationJob.created_at.desc(), PublicationJob.id.desc()),
            )
            .label("position"),
        ).where(
            PublicationJob.article_id.in_(article_ids),
            or_(PublicationJob.target_channels.contains([channel]), PublicationJob.target_channels == []),
        )

    async def jobs(self, article_id: UUID) -> tuple[list[PublicationJob], int]:
        total = await self.session.scalar(
            select(func.count(PublicationJob.id)).where(PublicationJob.article_id == article_id)
        )
        statement = (
            select(PublicationJob)
            .where(PublicationJob.article_id == article_id)
            .order_by(PublicationJob.created_at.desc(), PublicationJob.id.desc())
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
