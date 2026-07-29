"""跨渠道交付编排：每个外部结果先持久化，再推进后续阶段。"""

import hashlib
import logging
import shutil
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Protocol, cast
from uuid import UUID

from reven.domain import JobStatus, TargetChannel
from reven.jobs.errors import BlockedPublishError, PermanentPublishError, TransientPublishError
from reven.jobs.repository import JobClaim
from reven.publishing.notifications import DeliveryNotifier, Notification

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PendingNotification:
    fingerprint: str
    event: str
    stage: str
    summary: str
    error_code: str | None
    channel: TargetChannel | None


@dataclass(frozen=True)
class DeliveryRecord:
    job_id: UUID
    article_id: UUID
    notion_page_id: str
    notion_url: str
    reven_url: str
    title: str
    target_channels: tuple[TargetChannel, ...]
    used_default: bool
    channel_statuses: dict[TargetChannel, str]
    channel_results: dict[TargetChannel, dict[str, object]]
    final_status: JobStatus | None
    final_reason: str
    notion_pending: bool
    cleanup_pending: bool
    notifications: tuple[PendingNotification, ...]
    workspace_anchor: Path
    workspace: Path


class DeliveryStore(Protocol):
    async def load(self, claim: JobClaim) -> DeliveryRecord: ...
    async def ensure_default_event(self, claim: JobClaim) -> DeliveryRecord: ...
    async def channel_succeeded(
        self, claim: JobClaim, channel: TargetChannel, result: dict[str, object]
    ) -> DeliveryRecord: ...
    async def channel_failed(
        self,
        claim: JobClaim,
        channel: TargetChannel,
        status: JobStatus,
        reason: str,
        error_code: str,
    ) -> DeliveryRecord: ...
    async def begin_delivery(self, claim: JobClaim, status: JobStatus, reason: str) -> DeliveryRecord: ...
    async def finish_delivery(self, claim: JobClaim) -> DeliveryRecord: ...
    async def resolve_notification(self, claim: JobClaim, fingerprint: str, *, sent: bool) -> bool: ...
    async def finish_cleanup(self, claim: JobClaim) -> bool: ...
    async def bump_notification_revision(self, claim: JobClaim) -> int: ...


class ChannelPublisher(Protocol):
    async def publish(self, claim: JobClaim) -> object: ...


class NotionDeliveryWriter(Protocol):
    async def write(self, record: DeliveryRecord, status: JobStatus, reason: str) -> None: ...


class PublicationOrchestrator:
    def __init__(
        self,
        store: DeliveryStore,
        blog: ChannelPublisher,
        wechat: ChannelPublisher,
        notion: NotionDeliveryWriter,
        notifier: DeliveryNotifier,
    ) -> None:
        self.store = store
        self.publishers = {TargetChannel.BLOG: blog, TargetChannel.WECHAT: wechat}
        self.notion = notion
        self.notifier = notifier

    async def execute(self, claim: JobClaim) -> None:
        record = await self.store.load(claim)
        if not _is_finalized(record):
            record = await self.store.ensure_default_event(claim)
            await self._drain_notifications(claim, record)
            record = await self.store.load(claim)
            record = await self._publish_channels(claim, record)
            status, reason = _aggregate(record)
            record = await self.store.begin_delivery(claim, status, reason)
        if record.notion_pending:
            await self.notion.write(record, _required_status(record), record.final_reason)
            record = await self.store.finish_delivery(claim)
        await self._drain_notifications(claim, record)
        await self._cleanup(claim, record)

    async def _publish_channels(self, claim: JobClaim, record: DeliveryRecord) -> DeliveryRecord:
        for channel in record.target_channels:
            if _channel_finished(record, channel):
                continue
            try:
                result = await self.publishers[channel].publish(claim)
                record = await self.store.channel_succeeded(claim, channel, _result_dict(result))
            except TransientPublishError:
                raise
            except BlockedPublishError as exc:
                record = await self._record_failure(claim, channel, JobStatus.BLOCKED, exc)
            except PermanentPublishError as exc:
                record = await self._record_failure(claim, channel, JobStatus.FAILED, exc)
            await self._drain_notifications(claim, record)
        return record

    async def _record_failure(
        self,
        claim: JobClaim,
        channel: TargetChannel,
        status: JobStatus,
        error: Exception,
    ) -> DeliveryRecord:
        return await self.store.channel_failed(
            claim,
            channel,
            status,
            str(error),
            error_fingerprint(error),
        )

    async def _drain_notifications(self, claim: JobClaim, record: DeliveryRecord) -> None:
        for event in record.notifications:
            sent = False
            try:
                await self.notifier.send(_notification(record, event))
                sent = True
            except Exception as exc:
                logger.warning("飞书通知失败（error_type=%s）", type(exc).__name__)
            try:
                await self.store.resolve_notification(claim, event.fingerprint, sent=sent)
            except Exception as exc:
                logger.warning("飞书通知状态写入失败（error_type=%s）", type(exc).__name__)

    async def _cleanup(self, claim: JobClaim, record: DeliveryRecord) -> None:
        if not record.cleanup_pending:
            return
        try:
            cleanup_workspace(record.workspace, record.workspace_anchor)
        except OSError as exc:
            logger.warning("发布工作目录清理失败（error_type=%s）", type(exc).__name__)
            return
        try:
            await self.store.finish_cleanup(claim)
        except Exception as exc:
            logger.warning("清理状态写入失败（error_type=%s）", type(exc).__name__)


def notification_fingerprint(
    job_id: UUID,
    event: str,
    error_code: str | None,
    channel: TargetChannel | None,
) -> str:
    value = f"{job_id}:{event}:{error_code or ''}:{channel or ''}"
    return hashlib.sha256(value.encode()).hexdigest()


def error_fingerprint(error: Exception) -> str:
    payload = f"{type(error).__name__}:{str(error)}"
    return hashlib.sha256(payload.encode()).hexdigest()


def cleanup_workspace(workspace: Path, anchor: Path) -> None:
    _validate_cleanup_path(workspace, anchor)
    if not workspace.exists():
        return
    _validate_cleanup_path(workspace, anchor)
    shutil.rmtree(workspace)


def _validate_cleanup_path(workspace: Path, anchor: Path) -> None:
    try:
        UUID(workspace.name)
    except ValueError as exc:
        raise OSError("工作目录名称不是 Job UUID") from exc
    lexical_anchor = anchor.absolute()
    lexical_workspace = workspace.absolute()
    if lexical_workspace.parent != lexical_anchor:
        raise OSError("工作目录不在受控 jobs 目录下")
    _reject_symlink_components(lexical_anchor)
    if lexical_workspace.is_symlink():
        raise OSError("工作目录不能是符号链接")
    try:
        relative = lexical_workspace.resolve(strict=False).relative_to(lexical_anchor.resolve(strict=False))
    except ValueError as exc:
        raise OSError("工作目录规范路径越界") from exc
    if relative.parts != (workspace.name,):
        raise OSError("工作目录规范路径无效")


def _reject_symlink_components(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink():
            raise OSError("工作目录锚点包含符号链接")


def _is_finalized(record: DeliveryRecord) -> bool:
    return record.final_status is not None


def _channel_finished(record: DeliveryRecord, channel: TargetChannel) -> bool:
    return record.channel_statuses.get(channel) in {"已上线", "草稿已生成", "失败"}


def _aggregate(record: DeliveryRecord) -> tuple[JobStatus, str]:
    failures: list[dict[str, object]] = []
    for result in record.channel_results.values():
        failure = result.get("delivery_failure")
        if isinstance(failure, dict):
            failures.append(cast(dict[str, object], failure))
    if not failures:
        return JobStatus.COMPLETED, ""
    blocked = any(item.get("status") == JobStatus.BLOCKED for item in failures)
    reasons = [str(item.get("reason", "")) for item in failures]
    return (JobStatus.BLOCKED if blocked else JobStatus.FAILED), "；".join(reasons)[:1000]


def _required_status(record: DeliveryRecord) -> JobStatus:
    if record.final_status is None:
        raise RuntimeError("交付终态缺失")
    return record.final_status


def _result_dict(result: object) -> dict[str, object]:
    if isinstance(result, dict):
        return cast(dict[str, object], result)
    if is_dataclass(result) and not isinstance(result, type):
        return cast(dict[str, object], asdict(result))
    raise RuntimeError("渠道发布结果格式无效")


def _notification(record: DeliveryRecord, event: PendingNotification) -> Notification:
    return Notification(
        record.title,
        event.stage,
        event.summary,
        _links(record),
    )


def _links(record: DeliveryRecord) -> dict[str, str]:
    links = {"Notion": record.notion_url, "Reven": record.reven_url}
    blog = record.channel_results.get(TargetChannel.BLOG, {})
    for label, key in (("博客", "article_url"), ("PR", "pull_request_url")):
        value = blog.get(key)
        if isinstance(value, str):
            links[label] = value
    return links
