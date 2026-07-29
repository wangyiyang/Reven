from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from reven.domain import JobStatus, TargetChannel
from reven.jobs.errors import (
    BlockedPublishError,
    PermanentPublishError,
    TransientPublishError,
)
from reven.jobs.repository import JobClaim
from reven.publishing.orchestrator import (
    DeliveryRecord,
    Notification,
    PendingNotification,
    PublicationOrchestrator,
    cleanup_workspace,
    error_fingerprint,
    notification_fingerprint,
)


class FakeStore:
    def __init__(self, record: DeliveryRecord) -> None:
        self.record = record
        self.revision = 0
        self.sent: set[str] = set()
        self.events: list[str] = []

    async def load(self, claim: JobClaim) -> DeliveryRecord:
        del claim
        return self.record

    async def ensure_default_event(self, claim: JobClaim) -> DeliveryRecord:
        del claim
        if self.record.used_default and "default" not in self.events:
            self.events.append("default")
            self.record = self._queue("default_channels", "默认双渠道")
        return self.record

    async def channel_succeeded(
        self, claim: JobClaim, channel: TargetChannel, result: dict[str, object]
    ) -> DeliveryRecord:
        del claim
        statuses = dict(self.record.channel_statuses)
        statuses[channel] = "已上线" if channel == TargetChannel.BLOG else "草稿已生成"
        results = dict(self.record.channel_results)
        results[channel] = result
        self.record = replace(self.record, channel_statuses=statuses, channel_results=results)
        return self._queue(f"{channel}:success", "渠道成功", channel=channel)

    async def channel_failed(
        self,
        claim: JobClaim,
        channel: TargetChannel,
        status: JobStatus,
        reason: str,
        error_code: str,
    ) -> DeliveryRecord:
        del claim
        statuses = dict(self.record.channel_statuses)
        statuses[channel] = "失败"
        results = dict(self.record.channel_results)
        results[channel] = {
            "delivery_failure": {
                "status": status,
                "reason": reason,
                "error_code": error_code,
            }
        }
        self.record = replace(self.record, channel_statuses=statuses, channel_results=results)
        return self._queue("channel_failed", "渠道失败", error_code, channel)

    async def begin_delivery(self, claim: JobClaim, status: JobStatus, reason: str) -> DeliveryRecord:
        del claim
        self.record = replace(
            self.record,
            final_status=status,
            final_reason=reason,
            notion_pending=True,
        )
        return self.record

    async def finish_delivery(self, claim: JobClaim) -> DeliveryRecord:
        del claim
        self.record = replace(self.record, notion_pending=False, cleanup_pending=True)
        return self._queue("final", "交付结束")

    async def resolve_notification(self, claim: JobClaim, fingerprint: str, *, sent: bool) -> bool:
        del claim
        if sent:
            self.sent.add(fingerprint)
        self.record = replace(
            self.record,
            notifications=tuple(event for event in self.record.notifications if event.fingerprint != fingerprint),
        )
        return True

    async def finish_cleanup(self, claim: JobClaim) -> bool:
        del claim
        self.record = replace(self.record, cleanup_pending=False)
        return True

    async def bump_notification_revision(self, claim: JobClaim) -> int:
        del claim
        self.revision += 1
        return self.revision

    def _queue(
        self,
        event: str,
        stage: str,
        error_code: str | None = None,
        channel: TargetChannel | None = None,
    ) -> DeliveryRecord:
        self.revision += 1
        name = f"{event}:r{self.revision}"
        pending = PendingNotification(
            notification_fingerprint(self.record.job_id, name, error_code, channel),
            name,
            stage,
            stage,
            error_code,
            channel,
        )
        self.record = replace(self.record, notifications=(*self.record.notifications, pending))
        return self.record


class FakePublisher:
    def __init__(self, result: dict[str, object]) -> None:
        self.result = result
        self.calls = 0
        self.error: Exception | None = None

    async def publish(self, claim: JobClaim) -> dict[str, object]:
        del claim
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


class FakeNotion:
    def __init__(self) -> None:
        self.calls: list[JobStatus] = []
        self.error: Exception | None = None

    async def write(self, record: DeliveryRecord, status: JobStatus, reason: str) -> None:
        del record, reason
        self.calls.append(status)
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


def make_record(tmp_path: Path, *, used_default: bool = False) -> DeliveryRecord:
    job_id = uuid4()
    return DeliveryRecord(
        job_id,
        uuid4(),
        "page",
        "https://www.notion.so/page",
        f"https://dev.example.com/articles/{job_id}",
        "稿件",
        (TargetChannel.BLOG, TargetChannel.WECHAT),
        used_default,
        {TargetChannel.BLOG: "待处理", TargetChannel.WECHAT: "待处理"},
        {TargetChannel.BLOG: {}, TargetChannel.WECHAT: {}},
        None,
        "",
        False,
        False,
        (),
        tmp_path / "jobs",
        tmp_path / "jobs" / str(job_id),
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("failed_channel", "error", "expected_status"),
    [
        (TargetChannel.BLOG, PermanentPublishError("bad"), JobStatus.FAILED),
        (TargetChannel.WECHAT, BlockedPublishError("config"), JobStatus.BLOCKED),
    ],
)
async def test_terminal_channel_failure_still_runs_other_channel(
    tmp_path: Path,
    failed_channel: TargetChannel,
    error: Exception,
    expected_status: JobStatus,
) -> None:
    current = make_record(tmp_path)
    store = FakeStore(current)
    blog = FakePublisher({"article_url": "https://blog.example/post"})
    wechat = FakePublisher({"media_id": "draft"})
    (blog if failed_channel == TargetChannel.BLOG else wechat).error = error
    notion = FakeNotion()

    await PublicationOrchestrator(store, blog, wechat, notion, FakeNotifier()).execute(
        JobClaim(current.job_id, uuid4())
    )

    assert (blog.calls, wechat.calls) == (1, 1)
    assert notion.calls == [expected_status]
    assert store.record.final_status == expected_status


@pytest.mark.anyio
async def test_transient_stops_and_retry_skips_successful_channel(tmp_path: Path) -> None:
    current = make_record(tmp_path)
    store = FakeStore(current)
    blog = FakePublisher({"article_url": "https://blog.example/post"})
    wechat = FakePublisher({"media_id": "draft"})
    wechat.error = TransientPublishError("later")
    orchestrator = PublicationOrchestrator(store, blog, wechat, FakeNotion(), FakeNotifier())
    claim = JobClaim(current.job_id, uuid4())

    with pytest.raises(TransientPublishError):
        await orchestrator.execute(claim)
    wechat.error = None
    await orchestrator.execute(claim)

    assert blog.calls == 1
    assert wechat.calls == 2


@pytest.mark.anyio
async def test_default_and_channel_events_include_safe_links(tmp_path: Path) -> None:
    current = make_record(tmp_path, used_default=True)
    store = FakeStore(current)
    notifier = FakeNotifier()
    blog = FakePublisher(
        {
            "article_url": "https://blog.example/post",
            "pull_request_url": "https://github.com/acme/blog/pull/1",
        }
    )
    orchestrator = PublicationOrchestrator(store, blog, FakePublisher({"media_id": "draft"}), FakeNotion(), notifier)

    await orchestrator.execute(JobClaim(current.job_id, uuid4()))

    assert len(notifier.calls) == 4
    assert {"Notion", "Reven", "博客", "PR"} <= set(notifier.calls[-1].links)
    assert len(store.sent) == 4
    assert error_fingerprint(PermanentPublishError("same")) == error_fingerprint(PermanentPublishError("same"))


@pytest.mark.anyio
async def test_feishu_failure_does_not_change_delivery(tmp_path: Path) -> None:
    current = make_record(tmp_path)
    store = FakeStore(current)
    notifier = FakeNotifier()
    notifier.error = RuntimeError("down")

    await PublicationOrchestrator(
        store,
        FakePublisher({"article_url": "https://blog.example/post"}),
        FakePublisher({"media_id": "draft"}),
        FakeNotion(),
        notifier,
    ).execute(JobClaim(current.job_id, uuid4()))

    assert store.record.final_status == JobStatus.COMPLETED
    assert store.record.notifications == ()


@pytest.mark.parametrize("symlink_level", ["root", "jobs", "target"])
def test_cleanup_rejects_symlink_components_without_deleting_outside(
    tmp_path: Path,
    symlink_level: str,
) -> None:
    outside = tmp_path / "outside"
    victim = outside / "victim.txt"
    outside.mkdir()
    victim.write_text("keep", encoding="utf-8")
    job_id = str(uuid4())
    trusted_root = tmp_path / "trusted"
    if symlink_level == "root":
        trusted_root.symlink_to(outside, target_is_directory=True)
        anchor = trusted_root / "jobs"
        workspace = anchor / job_id
    elif symlink_level == "jobs":
        trusted_root.mkdir()
        anchor = trusted_root / "jobs"
        anchor.symlink_to(outside, target_is_directory=True)
        workspace = anchor / job_id
    else:
        anchor = trusted_root / "jobs"
        anchor.mkdir(parents=True)
        workspace = anchor / job_id
        workspace.symlink_to(outside, target_is_directory=True)

    with pytest.raises(OSError, match="符号链接"):
        cleanup_workspace(workspace, anchor)

    assert victim.read_text(encoding="utf-8") == "keep"
