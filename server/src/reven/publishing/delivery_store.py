"""跨渠道编排的租约隔离持久化。"""

from pathlib import Path
from typing import Any, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.articles.models import Article
from reven.domain import AutomationStatus, JobStatus, TargetChannel
from reven.jobs.errors import TransientPublishError
from reven.jobs.models import PublicationJob
from reven.jobs.repository import JobClaim
from reven.publishing.orchestrator import (
    DeliveryRecord,
    PendingNotification,
    notification_fingerprint,
)

_DELIVERY_KEY = "delivery_finalization"
_EVENTS_KEY = "delivery_notification_events"
_REVISION_KEY = "_revision"


class SqlAlchemyDeliveryStore:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        workspace_root: Path,
        public_base_url: str = "https://dev.wangyiyang.cc",
    ) -> None:
        self.session_factory = session_factory
        self.workspace_root = workspace_root
        self.public_base_url = public_base_url.rstrip("/")

    async def load(self, claim: JobClaim) -> DeliveryRecord:
        async with self.session_factory() as session:
            job, article = await _pair(session, claim.job_id)
            await _require_lease(session, job, claim)
            return self._record(job, article)

    async def ensure_default_event(self, claim: JobClaim) -> DeliveryRecord:
        async with self.session_factory.begin() as session:
            job, article = await _locked_pair(session, claim)
            if _used_default(job) and not job.notification_state.get("_default_event_created"):
                revision = _next_revision(job)
                _enqueue(job, "default_channels", "默认双渠道", "未选择目标渠道，已采用博客和微信公众号。", revision)
                job.notification_state = {**job.notification_state, "_default_event_created": True}
            return self._record(job, article)

    async def channel_succeeded(
        self,
        claim: JobClaim,
        channel: TargetChannel,
        result: dict[str, object],
    ) -> DeliveryRecord:
        async with self.session_factory.begin() as session:
            job, article = await _locked_pair(session, claim)
            revision = _next_revision(job)
            if channel == TargetChannel.BLOG:
                job.blog_status = "已上线"
                job.blog_result = {**job.blog_result, **result}
                _enqueue(job, "blog_online", "博客已上线", "博客文章已经上线。", revision, channel=channel)
            else:
                job.wechat_status = "草稿已生成"
                job.wechat_result = {**job.wechat_result, **result}
                _enqueue(job, "wechat_draft", "微信草稿已生成", "微信公众号草稿已生成。", revision, channel=channel)
            await session.flush()
            return self._record(job, article)

    async def channel_failed(
        self,
        claim: JobClaim,
        channel: TargetChannel,
        status: JobStatus,
        reason: str,
        error_code: str,
    ) -> DeliveryRecord:
        async with self.session_factory.begin() as session:
            job, article = await _locked_pair(session, claim)
            revision = _next_revision(job)
            failure = {"status": status, "reason": reason, "error_code": error_code}
            if channel == TargetChannel.BLOG:
                job.blog_status, job.blog_error = "失败", reason
                job.blog_result = {**job.blog_result, "delivery_failure": failure}
            else:
                job.wechat_status, job.wechat_error = "失败", reason
                job.wechat_result = {**job.wechat_result, "delivery_failure": failure}
            _enqueue(job, "channel_failed", "渠道发布失败", "该渠道需要人工处理。", revision, error_code, channel)
            await session.flush()
            return self._record(job, article)

    async def begin_delivery(self, claim: JobClaim, status: JobStatus, reason: str) -> DeliveryRecord:
        async with self.session_factory.begin() as session:
            job, article = await _locked_pair(session, claim)
            if status in {JobStatus.BLOCKED, JobStatus.FAILED}:
                article.automation_status = (
                    AutomationStatus.BLOCKED if status == JobStatus.BLOCKED else AutomationStatus.FAILED
                )
                article.last_error = reason
            job.snapshot_metadata = {
                **job.snapshot_metadata,
                _DELIVERY_KEY: {
                    "final_status": status,
                    "reason": reason,
                    "notion_pending": True,
                    "cleanup_pending": False,
                },
            }
            return self._record(job, article)

    async def finish_delivery(self, claim: JobClaim) -> DeliveryRecord:
        async with self.session_factory.begin() as session:
            job, article = await _locked_pair(session, claim)
            state = _delivery(job)
            status = JobStatus(str(state["final_status"]))
            revision = _next_revision(job)
            state.update(notion_pending=False, cleanup_pending=True)
            _set_delivery(job, state)
            finished_at = await session.scalar(select(func.clock_timestamp()))
            _apply_terminal(job, article, status, str(state.get("reason", "")), finished_at)
            event = "all_completed" if status == JobStatus.COMPLETED else "delivery_terminal"
            stage = "全部渠道已完成" if status == JobStatus.COMPLETED else str(status)
            summary = (
                "所有目标渠道已经交付。" if status == JobStatus.COMPLETED else "渠道交付结束，需要人工处理失败项。"
            )
            _enqueue(job, event, stage, summary, revision, str(status))
            await session.flush()
            return self._record(job, article)

    async def resolve_notification(self, claim: JobClaim, fingerprint: str, *, sent: bool) -> bool:
        async with self.session_factory.begin() as session:
            job, _article = await _locked_pair(session, claim)
            events = [item for item in _events(job) if item.get("fingerprint") != fingerprint]
            _set_events(job, events)
            if sent:
                job.notification_state = {
                    **job.notification_state,
                    fingerprint: {"sent": True},
                }
            _clear_finalization_if_done(job)
            return True

    async def finish_cleanup(self, claim: JobClaim) -> bool:
        async with self.session_factory.begin() as session:
            job, _article = await _locked_pair(session, claim)
            state = _delivery(job)
            state["cleanup_pending"] = False
            _set_delivery(job, state)
            _clear_finalization_if_done(job)
            return True

    async def bump_notification_revision(self, claim: JobClaim) -> int:
        async with self.session_factory.begin() as session:
            job, _article = await _locked_pair(session, claim)
            return _next_revision(job)

    def _record(self, job: PublicationJob, article: Article) -> DeliveryRecord:
        state = _delivery(job)
        final_raw = state.get("final_status")
        final_status = JobStatus(str(final_raw)) if final_raw else None
        return DeliveryRecord(
            job.id,
            article.id,
            article.notion_page_id,
            article.notion_url,
            f"{self.public_base_url}/articles/{article.id}",
            article.title,
            tuple(TargetChannel(value) for value in job.target_channels),
            _used_default(job),
            {TargetChannel.BLOG: job.blog_status, TargetChannel.WECHAT: job.wechat_status},
            {TargetChannel.BLOG: job.blog_result, TargetChannel.WECHAT: job.wechat_result},
            final_status,
            str(state.get("reason", "")),
            state.get("notion_pending") is True,
            state.get("cleanup_pending") is True,
            tuple(_notification(item) for item in _events(job)),
            self.workspace_root / "jobs",
            self.workspace_root / "jobs" / str(job.id),
        )


async def _pair(session: AsyncSession, job_id: UUID) -> tuple[PublicationJob, Article]:
    row = await session.execute(
        select(PublicationJob, Article)
        .join(Article, Article.id == PublicationJob.article_id)
        .where(PublicationJob.id == job_id)
    )
    pair = row.one_or_none()
    if pair is None:
        raise RuntimeError("发布任务不存在")
    return cast(tuple[PublicationJob, Article], pair)


async def _locked_pair(session: AsyncSession, claim: JobClaim) -> tuple[PublicationJob, Article]:
    row = await session.execute(
        select(PublicationJob, Article)
        .join(Article, Article.id == PublicationJob.article_id)
        .where(PublicationJob.id == claim.job_id)
        .with_for_update()
    )
    pair = row.one_or_none()
    if pair is None:
        raise RuntimeError("发布任务不存在")
    job, article = cast(tuple[PublicationJob, Article], pair)
    await _require_lease(session, job, claim)
    return job, article


async def _require_lease(session: AsyncSession, job: PublicationJob, claim: JobClaim) -> None:
    now = await session.scalar(select(func.clock_timestamp()))
    if (
        now is None
        or job.lease_token != claim.lease_token
        or job.lease_expires_at is None
        or job.lease_expires_at < now
    ):
        raise TransientPublishError("发布任务租约已丢失")


def _next_revision(job: PublicationJob) -> int:
    current = job.notification_state.get(_REVISION_KEY, 0)
    revision = (current if isinstance(current, int) else 0) + 1
    job.notification_state = {**job.notification_state, _REVISION_KEY: revision}
    return revision


def _enqueue(
    job: PublicationJob,
    event: str,
    stage: str,
    summary: str,
    revision: int,
    error_code: str | None = None,
    channel: TargetChannel | None = None,
) -> None:
    name = f"{event}:r{revision}"
    fingerprint = notification_fingerprint(job.id, name, error_code, channel)
    events = _events(job)
    events.append(
        {
            "fingerprint": fingerprint,
            "event": name,
            "stage": stage,
            "summary": summary,
            "error_code": error_code,
            "channel": channel,
        }
    )
    _set_events(job, events)


def _events(job: PublicationJob) -> list[dict[str, Any]]:
    value = job.snapshot_metadata.get(_EVENTS_KEY, [])
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _set_events(job: PublicationJob, events: list[dict[str, Any]]) -> None:
    job.snapshot_metadata = {**job.snapshot_metadata, _EVENTS_KEY: events}


def _notification(item: dict[str, Any]) -> PendingNotification:
    raw_channel = item.get("channel")
    channel = TargetChannel(str(raw_channel)) if raw_channel else None
    return PendingNotification(
        str(item["fingerprint"]),
        str(item["event"]),
        str(item["stage"]),
        str(item["summary"]),
        str(item["error_code"]) if item.get("error_code") else None,
        channel,
    )


def _delivery(job: PublicationJob) -> dict[str, Any]:
    value = job.snapshot_metadata.get(_DELIVERY_KEY, {})
    return dict(value) if isinstance(value, dict) else {}


def _set_delivery(job: PublicationJob, state: dict[str, Any]) -> None:
    job.snapshot_metadata = {**job.snapshot_metadata, _DELIVERY_KEY: state}


def _clear_finalization_if_done(job: PublicationJob) -> None:
    state = _delivery(job)
    if _events(job) or state.get("cleanup_pending") is True:
        return
    job.snapshot_metadata = {
        key: value for key, value in job.snapshot_metadata.items() if key not in {_DELIVERY_KEY, _EVENTS_KEY}
    }


def _used_default(job: PublicationJob) -> bool:
    return job.snapshot_metadata.get("target_channels_used_default") is True


def _apply_terminal(
    job: PublicationJob,
    article: Article,
    status: JobStatus,
    reason: str,
    finished_at: Any,
) -> None:
    job.overall_status = status
    job.finished_at = finished_at
    article.last_error = reason or None
    if status == JobStatus.COMPLETED:
        article.automation_status = AutomationStatus.COMPLETED
        article.notion_status = "已交付"
    else:
        article.automation_status = AutomationStatus.BLOCKED if status == JobStatus.BLOCKED else AutomationStatus.FAILED
