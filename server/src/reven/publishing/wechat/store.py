from typing import cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.articles.models import Article
from reven.jobs.models import PublicationJob
from reven.jobs.repository import JobClaim


class SqlAlchemyWeChatResultStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], *, author: str = "") -> None:
        self.session_factory = session_factory
        self.author = author

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
            return _job_data(job, article, self.author)

    async def assert_lease(self, claim: JobClaim) -> bool:
        async with self.session_factory() as session:
            now = func.clock_timestamp()
            statement = select(PublicationJob.id).where(
                PublicationJob.id == claim.job_id,
                PublicationJob.lease_token == claim.lease_token,
                PublicationJob.lease_expires_at >= now,
            )
            return await session.scalar(statement) is not None

    async def save_result(self, claim: JobClaim, patch: dict[str, object]) -> bool:
        async with self.session_factory.begin() as session:
            job = await _locked_job(session, claim.job_id)
            if job is None or not await _lease_matches(session, job, claim):
                return False
            job.wechat_result = {**job.wechat_result, **patch}
            return True

    async def clear_inflight_if_operation_matches(self, job_id: UUID, operation_key: str, operation_id: str) -> bool:
        async with self.session_factory.begin() as session:
            job = await _locked_job(session, job_id)
            if job is None or _operation_has_result(job.wechat_result, operation_key):
                return False
            operations = _operations(job.wechat_result)
            marker = operations.get(operation_key)
            if not isinstance(marker, dict) or marker.get("operation_id") != operation_id:
                return False
            operations.pop(operation_key)
            job.wechat_result = {**job.wechat_result, "operations_in_flight": operations}
            return True


async def _locked_job(session: AsyncSession, job_id: UUID) -> PublicationJob | None:
    job: PublicationJob | None = await session.scalar(
        select(PublicationJob).where(PublicationJob.id == job_id).with_for_update()
    )
    return job


async def _lease_matches(session: AsyncSession, job: PublicationJob, claim: JobClaim) -> bool:
    now = await session.scalar(select(func.clock_timestamp()))
    return bool(
        job.lease_token == claim.lease_token
        and job.lease_expires_at is not None
        and now is not None
        and job.lease_expires_at >= now
    )


def _operations(result: dict[str, object]) -> dict[str, dict[str, str]]:
    raw = result.get("operations_in_flight", {})
    if not isinstance(raw, dict):
        return {}
    return {
        key: dict(value)
        for key, value in cast(dict[str, dict[str, str]], raw).items()
        if isinstance(key, str) and isinstance(value, dict)
    }


def _operation_has_result(result: dict[str, object], key: str) -> bool:
    if key == "draft":
        return bool(result.get("media_id"))
    phase, _separator, sha256 = key.partition(":")
    if phase == "cover":
        return bool(result.get("thumb_media_id"))
    uploaded = result.get("uploaded_images")
    return isinstance(uploaded, dict) and bool(uploaded.get(sha256))


def _job_data(job: PublicationJob, article: Article, author: str) -> dict[str, object]:
    metadata = job.snapshot_metadata
    return {
        "source_markdown": job.source_markdown or "",
        "snapshot_metadata": metadata,
        "wechat_result": job.wechat_result,
        "title": metadata.get("title", article.title),
        "author": author or article.notion_metadata.get("author", ""),
        "digest": metadata.get("summary", ""),
        "content_source_url": article.notion_url,
    }
