"""Fenced persistence for recoverable blog publication phases."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.articles.models import Article
from reven.jobs.models import PublicationJob
from reven.jobs.repository import JobClaim


class SqlAlchemyBlogResultStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def load(self, claim: JobClaim) -> dict[str, object]:
        async with self.session_factory() as session:
            row = await session.execute(
                select(PublicationJob, Article)
                .join(Article, Article.id == PublicationJob.article_id)
                .where(PublicationJob.id == claim.job_id)
            )
            pair = row.one_or_none()
            if pair is None:
                raise RuntimeError("publication job missing")
            job, article = pair
            return {
                "page_id": article.notion_page_id,
                "title": str(job.snapshot_metadata.get("title", article.title)),
                "source_markdown": job.source_markdown or "",
                "content_hash": job.content_hash or "",
                "snapshot_metadata": job.snapshot_metadata,
                "blog_result": job.blog_result,
            }

    async def assert_lease(self, claim: JobClaim) -> bool:
        async with self.session_factory() as session:
            now = func.clock_timestamp()
            return (
                await session.scalar(
                    select(PublicationJob.id).where(
                        PublicationJob.id == claim.job_id,
                        PublicationJob.lease_token == claim.lease_token,
                        PublicationJob.lease_expires_at >= now,
                    )
                )
                is not None
            )

    async def save_result(self, claim: JobClaim, patch: dict[str, object]) -> bool:
        async with self.session_factory.begin() as session:
            job = await session.scalar(
                select(PublicationJob).where(PublicationJob.id == claim.job_id).with_for_update()
            )
            if job is None or not await _lease_matches(session, job, claim):
                return False
            job.blog_result = {**job.blog_result, **patch}
            return True

    async def clear_operation(self, claim: JobClaim, operation_id: str) -> bool:
        async with self.session_factory.begin() as session:
            job = await session.scalar(
                select(PublicationJob).where(PublicationJob.id == claim.job_id).with_for_update()
            )
            if job is None or not await _lease_matches(session, job, claim):
                return False
            marker = job.blog_result.get("operation")
            if not isinstance(marker, dict) or marker.get("id") != operation_id:
                return False
            job.blog_result = {key: value for key, value in job.blog_result.items() if key != "operation"}
            return True


async def _lease_matches(session: AsyncSession, job: PublicationJob, claim: JobClaim) -> bool:
    now = await session.scalar(select(func.clock_timestamp()))
    return bool(
        job.lease_token == claim.lease_token
        and job.lease_expires_at is not None
        and now is not None
        and job.lease_expires_at >= now
    )
