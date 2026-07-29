"""跨渠道交付编排：渠道结果持久化后再推进下一阶段。"""

import hashlib
import logging
import shutil
from dataclasses import asdict, dataclass, is_dataclass, replace
from pathlib import Path
from typing import Protocol, cast
from uuid import UUID

from reven.domain import JobStatus, TargetChannel
from reven.jobs.errors import (
    BlockedPublishError,
    PermanentPublishError,
    TransientPublishError,
)
from reven.jobs.repository import JobClaim

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeliveryRecord:
    job_id: UUID
    article_id: UUID
    notion_page_id: str
    notion_url: str
    title: str
    target_channels: tuple[TargetChannel, ...]
    channel_statuses: dict[TargetChannel, str]
    channel_results: dict[TargetChannel, dict[str, object]]
    pending_status: JobStatus | None
    pending_reason: str
    notification_revision: int
    workspace: Path

    def with_channels(
        self,
        statuses: dict[TargetChannel, str],
        results: dict[TargetChannel, dict[str, object]],
    ) -> "DeliveryRecord":
        return replace(self, channel_statuses=statuses, channel_results=results)

    def with_terminal(self, status: JobStatus, reason: str) -> "DeliveryRecord":
        return replace(self, pending_status=status, pending_reason=reason)

    def with_completion_pending(self) -> "DeliveryRecord":
        return replace(self, pending_status=JobStatus.COMPLETED, pending_reason="")


@dataclass(frozen=True)
class Notification:
    event: str
    title: str
    stage: str
    summary: str
    links: dict[str, str]
    error_code: str | None = None
    channel: TargetChannel | None = None


class DeliveryStore(Protocol):
    async def load(self, claim: JobClaim) -> DeliveryRecord: ...
    async def channel_succeeded(
        self, claim: JobClaim, channel: TargetChannel, result: dict[str, object]
    ) -> DeliveryRecord: ...
    async def begin_terminal(
        self,
        claim: JobClaim,
        status: JobStatus,
        reason: str,
        channel: TargetChannel,
    ) -> DeliveryRecord: ...
    async def finish_terminal(self, claim: JobClaim) -> None: ...
    async def begin_completion(self, claim: JobClaim) -> DeliveryRecord: ...
    async def finish_completion(self, claim: JobClaim) -> None: ...
    async def has_notification(self, claim: JobClaim, fingerprint: str) -> bool: ...
    async def record_notification(self, claim: JobClaim, fingerprint: str) -> bool: ...


class ChannelPublisher(Protocol):
    async def publish(self, claim: JobClaim) -> object: ...


class NotionDeliveryWriter(Protocol):
    async def write(self, record: DeliveryRecord, status: JobStatus, reason: str) -> None: ...


class DeliveryNotifier(Protocol):
    async def send(self, notification: Notification) -> None: ...


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
        self.publishers = {
            TargetChannel.BLOG: blog,
            TargetChannel.WECHAT: wechat,
        }
        self.notion = notion
        self.notifier = notifier

    async def execute(self, claim: JobClaim) -> None:
        record = await self.store.load(claim)
        if record.pending_status is not None:
            await self._finish_pending(claim, record)
            return
        for channel in record.target_channels:
            if _channel_complete(record, channel):
                continue
            try:
                result = await self.publishers[channel].publish(claim)
                record = await self.store.channel_succeeded(
                    claim, channel, _result_dict(result)
                )
            except TransientPublishError:
                raise
            except BlockedPublishError as exc:
                await self._begin_terminal(claim, record, JobStatus.BLOCKED, str(exc), channel)
                return
            except PermanentPublishError as exc:
                await self._begin_terminal(claim, record, JobStatus.FAILED, str(exc), channel)
                return
        record = await self.store.begin_completion(claim)
        await self._finish_pending(claim, record)

    async def _begin_terminal(
        self,
        claim: JobClaim,
        record: DeliveryRecord,
        status: JobStatus,
        reason: str,
        channel: TargetChannel,
    ) -> None:
        record = await self.store.begin_terminal(claim, status, reason, channel)
        await self._finish_pending(claim, record, channel=channel)

    async def _finish_pending(
        self,
        claim: JobClaim,
        record: DeliveryRecord,
        *,
        channel: TargetChannel | None = None,
    ) -> None:
        await self._write_and_finish(claim, record)
        if record.pending_status != JobStatus.COMPLETED:
            await self._notify(
                claim,
                record,
                Notification(
                    event=f"terminal:{record.pending_status}:r{record.notification_revision}",
                    title=record.title,
                    stage=record.pending_status or JobStatus.FAILED,
                    summary="发布需要人工处理，请在 Reven 查看失败原因。",
                    links={"Notion": record.notion_url},
                    error_code=str(record.pending_status),
                    channel=channel,
                ),
            )
            return
        await self._notify(
            claim,
            record,
            Notification(
                event=f"completed:r{record.notification_revision}",
                title=record.title,
                stage=JobStatus.COMPLETED,
                summary="所有目标渠道已经交付。",
                links=_completion_links(record),
            ),
        )
        _cleanup_workspace(record.workspace)

    async def _write_and_finish(self, claim: JobClaim, record: DeliveryRecord) -> None:
        status = record.pending_status
        if status is None:
            raise RuntimeError("交付状态缺少待回写阶段")
        await self.notion.write(record, status, record.pending_reason)
        if status == JobStatus.COMPLETED:
            await self.store.finish_completion(claim)
        else:
            await self.store.finish_terminal(claim)

    async def _notify(
        self, claim: JobClaim, record: DeliveryRecord, notification: Notification
    ) -> None:
        fingerprint = notification_fingerprint(
            record.job_id,
            notification.event,
            notification.error_code,
            notification.channel,
        )
        if await self.store.has_notification(claim, fingerprint):
            return
        try:
            await self.notifier.send(notification)
        except Exception as exc:
            logger.warning("飞书通知失败（error_type=%s）", type(exc).__name__)
            return
        try:
            recorded = await self.store.record_notification(claim, fingerprint)
        except TransientPublishError:
            recorded = False
        if not recorded:
            logger.warning("飞书通知已发送，但租约变化导致去重状态未写入")


def notification_fingerprint(
    job_id: UUID,
    event: str,
    error_code: str | None,
    channel: TargetChannel | None,
) -> str:
    value = f"{job_id}:{event}:{error_code or ''}:{channel or ''}"
    return hashlib.sha256(value.encode()).hexdigest()


def _channel_complete(record: DeliveryRecord, channel: TargetChannel) -> bool:
    expected = "已上线" if channel == TargetChannel.BLOG else "草稿已生成"
    return record.channel_statuses.get(channel) == expected


def _result_dict(result: object) -> dict[str, object]:
    if isinstance(result, dict):
        return cast(dict[str, object], result)
    if is_dataclass(result) and not isinstance(result, type):
        return cast(dict[str, object], asdict(result))
    raise RuntimeError("渠道发布结果格式无效")


def _completion_links(record: DeliveryRecord) -> dict[str, str]:
    links = {"Notion": record.notion_url}
    blog_url = record.channel_results.get(TargetChannel.BLOG, {}).get("article_url")
    if isinstance(blog_url, str):
        links["博客"] = blog_url
    return links


def _cleanup_workspace(workspace: Path) -> None:
    try:
        if workspace.exists():
            shutil.rmtree(workspace)
    except OSError as exc:
        logger.warning("发布工作目录清理失败（error_type=%s）", type(exc).__name__)
