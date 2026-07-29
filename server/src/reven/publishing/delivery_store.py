"""跨渠道编排的租约隔离持久化。"""

from pathlib import Path
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.articles.models import Article
from reven.domain import AutomationStatus, JobStatus, TargetChannel
from reven.jobs.errors import TransientPublishError
from reven.jobs.models import PublicationJob
from reven.jobs.repository import JobClaim
from reven.publishing.orchestrator import DeliveryRecord

_PENDING_KEY = "delivery_pending"


class SqlAlchemyDeliveryStore:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        workspace_root: Path,
    ) -> None:
        self.session_factory = session_factory
        self.workspace_root = workspace_root

    async def load(self, claim: JobClaim) -> DeliveryRecord:
        async with self.session_factory() as session:
            job, article = await _pair(session, claim.job_id)
            await _require_lease(session, job, claim)
            return _record(job, article, self.workspace_root)

    async def channel_succeeded(
        self,
        claim: JobClaim,
        channel: TargetChannel,
        result: dict[str, object],
    ) -> DeliveryRecord:
        async with self.session_factory.begin() as session:
            job, article = await _locked_pair(session, claim)
            if channel == TargetChannel.BLOG:
                job.blog_status = "已上线"
                job.blog_result = {**job.blog_result, **result}
            else:
                job.wechat_status = "草稿已生成"
                job.wechat_result = {**job.wechat_result, **result}
            await session.flush()
            return _record(job, article, self.workspace_root)

    async def begin_terminal(
        self,
        claim: JobClaim,
        status: JobStatus,
        reason: str,
        channel: TargetChannel,
    ) -> DeliveryRecord:
        if status not in (JobStatus.BLOCKED, JobStatus.FAILED):
            raise ValueError("终止状态无效")
        async with self.session_factory.begin() as session:
            job, article = await _locked_pair(session, claim)
            _set_pending(job, status, reason)
            if channel == TargetChannel.BLOG:
                job.blog_status = "失败"
                job.blog_error = reason
            else:
                job.wechat_status = "失败"
                job.wechat_error = reason
            article.last_error = reason
            article.automation_status = (
                AutomationStatus.BLOCKED if status == JobStatus.BLOCKED else AutomationStatus.FAILED
            )
            await session.flush()
            return _record(job, article, self.workspace_root)

    async def finish_terminal(self, claim: JobClaim) -> None:
        async with self.session_factory.begin() as session:
            job, _article = await _locked_pair(session, claim)
            pending = _pending(job)
            if pending[0] not in (JobStatus.BLOCKED, JobStatus.FAILED):
                raise RuntimeError("任务没有待完成的终止状态")
            job.overall_status = pending[0]
            _clear_pending(job)

    async def begin_completion(self, claim: JobClaim) -> DeliveryRecord:
        async with self.session_factory.begin() as session:
            job, article = await _locked_pair(session, claim)
            record = _record(job, article, self.workspace_root)
            if any(not _complete(record, channel) for channel in record.target_channels):
                raise RuntimeError("目标渠道尚未全部完成")
            _set_pending(job, JobStatus.COMPLETED, "")
            await session.flush()
            return _record(job, article, self.workspace_root)

    async def finish_completion(self, claim: JobClaim) -> None:
        async with self.session_factory.begin() as session:
            job, article = await _locked_pair(session, claim)
            if _pending(job)[0] != JobStatus.COMPLETED:
                raise RuntimeError("任务没有待完成的交付状态")
            job.overall_status = JobStatus.COMPLETED
            job.finished_at = await session.scalar(select(func.clock_timestamp()))
            _clear_pending(job)
            article.automation_status = AutomationStatus.COMPLETED
            article.notion_status = "已交付"
            article.last_error = None

    async def has_notification(self, claim: JobClaim, fingerprint: str) -> bool:
        async with self.session_factory() as session:
            job, _article = await _pair(session, claim.job_id)
            await _require_lease(session, job, claim)
            return fingerprint in job.notification_state

    async def record_notification(self, claim: JobClaim, fingerprint: str) -> bool:
        async with self.session_factory.begin() as session:
            job, _article = await _locked_pair(session, claim)
            if fingerprint in job.notification_state:
                return True
            job.notification_state = {
                **job.notification_state,
                fingerprint: {"sent": True},
            }
            return True


async def _pair(session: AsyncSession, job_id) -> tuple[PublicationJob, Article]:  # type: ignore[no-untyped-def]
    row = await session.execute(
        select(PublicationJob, Article)
        .join(Article, Article.id == PublicationJob.article_id)
        .where(PublicationJob.id == job_id)
    )
    pair = row.one_or_none()
    if pair is None:
        raise RuntimeError("发布任务不存在")
    return cast(tuple[PublicationJob, Article], pair)


async def _locked_pair(
    session: AsyncSession, claim: JobClaim
) -> tuple[PublicationJob, Article]:
    job, article = await _pair_for_update(session, claim)
    await _require_lease(session, job, claim)
    return job, article


async def _pair_for_update(
    session: AsyncSession, claim: JobClaim
) -> tuple[PublicationJob, Article]:
    row = await session.execute(
        select(PublicationJob, Article)
        .join(Article, Article.id == PublicationJob.article_id)
        .where(PublicationJob.id == claim.job_id)
        .with_for_update()
    )
    pair = row.one_or_none()
    if pair is None:
        raise RuntimeError("发布任务不存在")
    return cast(tuple[PublicationJob, Article], pair)


async def _require_lease(
    session: AsyncSession,
    job: PublicationJob,
    claim: JobClaim,
) -> None:
    now = await session.scalar(select(func.clock_timestamp()))
    if (
        now is None
        or job.lease_token != claim.lease_token
        or job.lease_expires_at is None
        or job.lease_expires_at < now
    ):
        raise TransientPublishError("发布任务租约已丢失")


def _record(
    job: PublicationJob,
    article: Article,
    workspace_root: Path,
) -> DeliveryRecord:
    pending_status, pending_reason = _pending(job)
    revision = job.notification_state.get("_revision", 0)
    return DeliveryRecord(
        job_id=job.id,
        article_id=article.id,
        notion_page_id=article.notion_page_id,
        notion_url=article.notion_url,
        title=article.title,
        target_channels=tuple(TargetChannel(value) for value in job.target_channels),
        channel_statuses={
            TargetChannel.BLOG: job.blog_status,
            TargetChannel.WECHAT: job.wechat_status,
        },
        channel_results={
            TargetChannel.BLOG: job.blog_result,
            TargetChannel.WECHAT: job.wechat_result,
        },
        pending_status=pending_status,
        pending_reason=pending_reason,
        notification_revision=revision if isinstance(revision, int) else 0,
        workspace=workspace_root / "jobs" / str(job.id),
    )


def _pending(job: PublicationJob) -> tuple[JobStatus | None, str]:
    value = job.snapshot_metadata.get(_PENDING_KEY)
    if not isinstance(value, dict):
        return None, ""
    raw_status = value.get("status")
    try:
        status = JobStatus(str(raw_status))
    except ValueError:
        return None, ""
    reason = value.get("reason")
    return status, reason if isinstance(reason, str) else ""


def _set_pending(job: PublicationJob, status: JobStatus, reason: str) -> None:
    job.snapshot_metadata = {
        **job.snapshot_metadata,
        _PENDING_KEY: {"status": status, "reason": reason},
    }


def _clear_pending(job: PublicationJob) -> None:
    job.snapshot_metadata = {
        key: value
        for key, value in job.snapshot_metadata.items()
        if key != _PENDING_KEY
    }


def _complete(record: DeliveryRecord, channel: TargetChannel) -> bool:
    expected = "已上线" if channel == TargetChannel.BLOG else "草稿已生成"
    return record.channel_statuses.get(channel) == expected
