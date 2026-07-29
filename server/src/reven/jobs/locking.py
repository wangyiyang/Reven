"""Canonical Article -> PublicationJob row-lock ordering."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from reven.articles.models import Article
from reven.jobs.models import PublicationJob


async def lock_article_job(
    session: AsyncSession,
    job_id: UUID,
    *,
    article_id: UUID | None = None,
) -> tuple[Article, PublicationJob] | None:
    resolved_id = await session.scalar(select(PublicationJob.article_id).where(PublicationJob.id == job_id))
    if resolved_id is None or (article_id is not None and resolved_id != article_id):
        return None
    article = await session.scalar(select(Article).where(Article.id == resolved_id).with_for_update())
    job = await session.scalar(
        select(PublicationJob)
        .where(PublicationJob.id == job_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if article is None or job is None or job.article_id != article.id:
        return None
    return article, job
