from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

import pytest
from reven.domain import JobStatus, TargetChannel
from reven.jobs.errors import BlockedPublishError, TransientPublishError
from reven.jobs.repository import JobClaim
from reven.publishing.orchestrator import (
    DeliveryRecord,
    Notification,
    PublicationOrchestrator,
)


@dataclass
class FakeStore:
    record: DeliveryRecord
    notifications: set[str] = field(default_factory=set)
    events: list[str] = field(default_factory=list)

    async def load(self, claim: JobClaim) -> DeliveryRecord:
        del claim
        return self.record

    async def channel_succeeded(
        self, claim: JobClaim, channel: TargetChannel, result: dict[str, object]
    ) -> DeliveryRecord:
        del claim
        self.events.append(f"{channel}:success")
        statuses = dict(self.record.channel_statuses)
        statuses[channel] = "已上线" if channel == TargetChannel.BLOG else "草稿已生成"
        results = dict(self.record.channel_results)
        results[channel] = result
        self.record = self.record.with_channels(statuses, results)
        return self.record

    async def begin_terminal(
        self,
        claim: JobClaim,
        status: JobStatus,
        reason: str,
        channel: TargetChannel,
    ) -> DeliveryRecord:
        del claim, channel
        self.events.append(f"terminal:{status}")
        self.record = self.record.with_terminal(status, reason)
        return self.record

    async def finish_terminal(self, claim: JobClaim) -> None:
        del claim
        self.events.append("terminal:finished")

    async def begin_completion(self, claim: JobClaim) -> DeliveryRecord:
        del claim
        self.events.append("completion:pending")
        self.record = self.record.with_completion_pending()
        return self.record

    async def finish_completion(self, claim: JobClaim) -> None:
        del claim
        self.events.append("completion:finished")

    async def has_notification(self, claim: JobClaim, fingerprint: str) -> bool:
        del claim
        return fingerprint in self.notifications

    async def record_notification(self, claim: JobClaim, fingerprint: str) -> bool:
        del claim
        self.notifications.add(fingerprint)
        return True


class FakePublisher:
    def __init__(self, result: dict[str, object]) -> None:
        self.result = result
        self.calls = 0
        self.error: Exception | None = None

    async def publish(self, claim: JobClaim) -> dict[str, object]:
        del claim
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result


class FakeNotion:
    def __init__(self) -> None:
        self.calls: list[tuple[JobStatus, str]] = []
        self.error: Exception | None = None

    async def write(self, record: DeliveryRecord, status: JobStatus, reason: str) -> None:
        del record
        self.calls.append((status, reason))
        if self.error:
            raise self.error


class FakeNotifier:
    def __init__(self) -> None:
        self.calls: list[Notification] = []
        self.error: Exception | None = None

    async def send(self, notification: Notification) -> None:
        self.calls.append(notification)
        if self.error:
            raise self.error


def record(tmp_path: Path) -> DeliveryRecord:
    return DeliveryRecord(
        job_id=uuid4(),
        article_id=uuid4(),
        notion_page_id="page",
        notion_url="https://www.notion.so/page",
        title="稿件",
        target_channels=(TargetChannel.BLOG, TargetChannel.WECHAT),
        channel_statuses={
            TargetChannel.BLOG: "待处理",
            TargetChannel.WECHAT: "待处理",
        },
        channel_results={
            TargetChannel.BLOG: {},
            TargetChannel.WECHAT: {},
        },
        pending_status=None,
        pending_reason="",
        notification_revision=0,
        workspace=tmp_path / "job",
    )


@pytest.mark.anyio
async def test_retry_only_runs_failed_channel(tmp_path: Path) -> None:
    current = record(tmp_path)
    current = current.with_channels(
        {
            TargetChannel.BLOG: "已上线",
            TargetChannel.WECHAT: "待处理",
        },
        {
            TargetChannel.BLOG: {"article_url": "https://www.wangyiyang.cc/post"},
            TargetChannel.WECHAT: {},
        },
    )
    store = FakeStore(current)
    blog = FakePublisher({"article_url": "should-not-run"})
    wechat = FakePublisher({"media_id": "draft"})
    wechat.error = TransientPublishError("later")
    notion = FakeNotion()
    orchestrator = PublicationOrchestrator(store, blog, wechat, notion, FakeNotifier())
    claim = JobClaim(current.job_id, uuid4())

    with pytest.raises(TransientPublishError):
        await orchestrator.execute(claim)
    wechat.error = None
    await orchestrator.execute(claim)

    assert blog.calls == 0
    assert wechat.calls == 2
    assert store.events[-1] == "completion:finished"


@pytest.mark.anyio
async def test_notion_retry_does_not_repeat_channels_and_cleanup_is_last(tmp_path: Path) -> None:
    current = record(tmp_path)
    current.workspace.mkdir()
    store = FakeStore(current)
    blog = FakePublisher({"article_url": "https://www.wangyiyang.cc/post"})
    wechat = FakePublisher({"media_id": "draft"})
    notion = FakeNotion()
    notion.error = TransientPublishError("notion down")
    orchestrator = PublicationOrchestrator(store, blog, wechat, notion, FakeNotifier())
    claim = JobClaim(current.job_id, uuid4())

    with pytest.raises(TransientPublishError):
        await orchestrator.execute(claim)
    assert current.workspace.exists()

    notion.error = None
    await orchestrator.execute(claim)

    assert (blog.calls, wechat.calls) == (1, 1)
    assert not current.workspace.exists()
    assert store.events[-1] == "completion:finished"


@pytest.mark.anyio
async def test_blocked_channel_records_terminal_state_and_notion(tmp_path: Path) -> None:
    current = record(tmp_path)
    store = FakeStore(current)
    blog = FakePublisher({})
    blog.error = BlockedPublishError("GitHub 未配置")
    notion = FakeNotion()
    orchestrator = PublicationOrchestrator(
        store, blog, FakePublisher({}), notion, FakeNotifier()
    )

    await orchestrator.execute(JobClaim(current.job_id, uuid4()))

    assert notion.calls == [(JobStatus.BLOCKED, "GitHub 未配置")]
    assert "terminal:finished" in store.events


@pytest.mark.anyio
async def test_notification_is_deduplicated_and_failure_is_non_fatal(tmp_path: Path) -> None:
    current = record(tmp_path)
    store = FakeStore(current)
    notifier = FakeNotifier()
    notifier.error = RuntimeError("feishu down")
    orchestrator = PublicationOrchestrator(
        store,
        FakePublisher({"article_url": "https://www.wangyiyang.cc/post"}),
        FakePublisher({"media_id": "draft"}),
        FakeNotion(),
        notifier,
    )
    claim = JobClaim(current.job_id, uuid4())

    await orchestrator.execute(claim)
    await orchestrator.execute(claim)

    assert len(notifier.calls) == 2
    assert store.notifications == set()


@pytest.mark.anyio
async def test_successful_notification_is_deduplicated(tmp_path: Path) -> None:
    current = record(tmp_path).with_terminal(JobStatus.BLOCKED, "需要配置")
    store = FakeStore(current)
    notifier = FakeNotifier()
    orchestrator = PublicationOrchestrator(
        store, FakePublisher({}), FakePublisher({}), FakeNotion(), notifier
    )
    claim = JobClaim(current.job_id, uuid4())

    await orchestrator.execute(claim)
    await orchestrator.execute(claim)

    assert len(notifier.calls) == 1
    assert len(store.notifications) == 1
