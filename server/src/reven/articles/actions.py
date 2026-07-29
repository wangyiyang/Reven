"""Transactional workbench actions with explicit state boundaries."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.articles.models import Article
from reven.domain import AutomationStatus, BlogStage, JobStatus, TargetChannel, WechatStage
from reven.jobs.locking import lock_article_job
from reven.jobs.models import PublicationJob
from reven.jobs.repository import JobRepository


@dataclass
class ActionConflictError(Exception):
    code: str
    message: str


class ArticleActionService:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self.factory = factory

    async def retry(self, article_id: UUID, job_id: UUID, channels: list[TargetChannel]) -> None:
        async with self.factory.begin() as session:
            article, job = await _locked_pair(session, article_id, job_id)
            _validate_retry(job, channels)
            revision = await JobRepository(session).bump_notification_revision_for_retry(job.id)
            if revision is None:
                raise ActionConflictError("JOB_BUSY", "任务正在执行或当前状态不可重试")
            _reset_channels(job, channels)
            job.snapshot_metadata = _retry_metadata(job.snapshot_metadata)
            job.overall_status = JobStatus.WAITING
            job.scheduled_at = await _database_now(session)
            job.finished_at = None
            article.automation_status = AutomationStatus.WAITING
            article.last_error = None

    async def cancel(self, article_id: UUID, job_id: UUID) -> None:
        async with self.factory.begin() as session:
            article, job = await _locked_pair(session, article_id, job_id)
            now = await _database_now(session)
            active_lease = (
                job.lease_token is not None and job.lease_expires_at is not None and job.lease_expires_at >= now
            )
            if (
                job.overall_status != JobStatus.WAITING
                or job.started_at is not None
                or job.attempt_count != 0
                or active_lease
                or job.snapshot_metadata.get("notion_write_pending") is True
                or job.snapshot_metadata.get("asset_finalize_pending") is True
            ):
                raise ActionConflictError("JOB_NOT_CANCELLABLE", "仅可取消尚未开始的等待任务")
            job.overall_status = JobStatus.CANCELLED
            job.lease_token = None
            job.lease_expires_at = None
            article.automation_status = AutomationStatus.NOT_STARTED


async def _locked_pair(
    session: AsyncSession,
    article_id: UUID,
    job_id: UUID,
) -> tuple[Article, PublicationJob]:
    pair = await lock_article_job(session, job_id, article_id=article_id)
    if pair is None:
        raise ActionConflictError("JOB_NOT_FOUND", "稿件或发布任务不存在")
    return pair


def _validate_retry(job: PublicationJob, channels: list[TargetChannel]) -> None:
    if job.overall_status not in {JobStatus.FAILED, JobStatus.BLOCKED}:
        raise ActionConflictError("JOB_NOT_RETRYABLE", "仅失败或阻塞任务可重试")
    targets = set(job.target_channels)
    if any(channel.value not in targets for channel in channels):
        raise ActionConflictError("CHANNEL_NOT_TARGETED", "只能重试该任务的目标渠道")
    invalid = [channel for channel in channels if not _channel_retryable(job, channel)]
    if invalid:
        raise ActionConflictError("CHANNEL_NOT_RETRYABLE", "只能重试失败或阻塞且尚未交付的渠道")


def _channel_retryable(job: PublicationJob, channel: TargetChannel) -> bool:
    status = job.blog_status if channel == TargetChannel.BLOG else job.wechat_status
    success = BlogStage.ONLINE if channel == TargetChannel.BLOG else WechatStage.DRAFT_CREATED
    return status != success and (status == "失败" or job.overall_status == JobStatus.BLOCKED)


def _reset_channels(job: PublicationJob, channels: list[TargetChannel]) -> None:
    if TargetChannel.BLOG in channels:
        job.blog_status = BlogStage.PENDING
        job.blog_error = None
        job.blog_result = _without_failure(job.blog_result)
        job.blog_attempt_count = 0
    if TargetChannel.WECHAT in channels:
        job.wechat_status = WechatStage.PENDING
        job.wechat_error = None
        job.wechat_result = _without_failure(job.wechat_result)
        job.wechat_attempt_count = 0


def _without_failure(result: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in result.items() if key != "delivery_failure"}


def _retry_metadata(metadata: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in metadata.items()
        if key not in {"delivery_finalization", "delivery_notification_events"}
    }


async def _database_now(session: AsyncSession):  # type: ignore[no-untyped-def]
    now = await session.scalar(select(func.clock_timestamp()))
    if now is None:
        raise RuntimeError("数据库未返回有效时间")
    return now
