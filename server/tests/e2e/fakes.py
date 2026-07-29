from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from reven.domain import JobStatus
from reven.jobs.errors import TransientPublishError
from reven.jobs.repository import JobClaim
from reven.publishing.assets import MaterializedAsset, MaterializedAssets
from reven.publishing.orchestrator import DeliveryRecord, Notification

PAGE_ID = "11111111-1111-1111-1111-111111111111"


def notion_page(
    *,
    edited_at: datetime,
    title: str = "端到端测试稿",
    channels: tuple[str, ...] = (),
    planned_at: str | None = None,
    has_cover: bool = True,
) -> dict[str, Any]:
    cover = (
        [{"type": "external", "name": "cover.png", "external": {"url": "https://assets.example/cover.png"}}]
        if has_cover
        else []
    )
    return {
        "id": PAGE_ID,
        "url": f"https://www.notion.so/{PAGE_ID.replace('-', '')}",
        "last_edited_time": edited_at.astimezone(UTC).isoformat(),
        "properties": {
            "标题": {"type": "title", "title": [{"plain_text": title}]},
            "状态": {"type": "status", "status": {"name": "待发布"}},
            "自动化状态": {"type": "select", "select": {"name": "未开始"}},
            "目标渠道": {
                "type": "multi_select",
                "multi_select": [{"name": channel} for channel in channels],
            },
            "计划发布日": {"type": "date", "date": {"start": planned_at} if planned_at else None},
            "摘要": {"type": "rich_text", "rich_text": [{"plain_text": "测试摘要"}]},
            "封面": {"type": "files", "files": cover},
        },
    }


class FakeNotion:
    def __init__(self, page: dict[str, Any], markdown: str = "第一版正文") -> None:
        self.page = deepcopy(page)
        self.markdown = markdown
        self.updates: list[dict[str, Any]] = []
        self.fail_delivery_writes = 0

    async def query_data_source(self, data_source_id: str, *, start_cursor: str | None = None) -> dict[str, Any]:
        assert data_source_id == "editorial"
        assert start_cursor is None
        return {"results": [deepcopy(self.page)], "has_more": False, "next_cursor": None}

    async def retrieve_page(self, page_id: str) -> dict[str, Any]:
        assert page_id == PAGE_ID
        return deepcopy(self.page)

    async def retrieve_page_markdown(self, page_id: str) -> str:
        assert page_id == PAGE_ID
        return self.markdown

    async def update_page(self, page_id: str, *, properties: dict[str, Any]) -> dict[str, Any]:
        assert page_id == PAGE_ID
        self.updates.append(deepcopy(properties))
        return {}

    def replace(
        self,
        *,
        edited_at: datetime,
        title: str | None = None,
        markdown: str | None = None,
        has_cover: bool | None = None,
    ) -> None:
        self.page["last_edited_time"] = edited_at.astimezone(UTC).isoformat()
        if title is not None:
            self.page["properties"]["标题"]["title"] = [{"plain_text": title}]
        if markdown is not None:
            self.markdown = markdown
        if has_cover is not None:
            self.page["properties"]["封面"]["files"] = (
                [
                    {
                        "type": "external",
                        "name": "cover.png",
                        "external": {"url": "https://assets.example/cover.png"},
                    }
                ]
                if has_cover
                else []
            )


class FakeMaterializer:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.calls = 0

    async def materialize(self, job_id: UUID, image_urls: list[str], cover_url: str | None) -> MaterializedAssets:
        del image_urls
        self.calls += 1
        cover = None
        if cover_url is not None:
            digest = hashlib.sha256(b"cover").hexdigest()
            cover = MaterializedAsset(cover_url, self.root / str(job_id) / "cover.png", digest, "image/png", 5)
        return MaterializedAssets((), cover)

    async def finalize(self, assets: MaterializedAssets) -> MaterializedAssets:
        return assets

    async def discard(self, assets: MaterializedAssets) -> None:
        del assets

    async def resume_finalize(
        self, job_id: UUID, staging_identity: str, expected_manifest: list[dict[str, str]]
    ) -> None:
        del job_id, staging_identity, expected_manifest


class FakePublisher:
    def __init__(self, result: dict[str, object]) -> None:
        self.result = result
        self.calls: list[JobClaim] = []
        self.transient_failures = 0

    async def publish(self, claim: JobClaim) -> dict[str, object]:
        self.calls.append(claim)
        if self.transient_failures:
            self.transient_failures -= 1
            raise TransientPublishError("fake transient failure")
        return deepcopy(self.result)


class FakeDeliveryWriter:
    def __init__(self, notion: FakeNotion) -> None:
        self.notion = notion
        self.calls: list[tuple[UUID, JobStatus]] = []

    async def write(self, record: DeliveryRecord, status: JobStatus, reason: str) -> None:
        del reason
        self.calls.append((record.job_id, status))
        if self.notion.fail_delivery_writes:
            self.notion.fail_delivery_writes -= 1
            raise TransientPublishError("fake notion write failure")
        self.notion.page["properties"]["状态"]["status"] = {
            "name": "已交付" if status == JobStatus.COMPLETED else "待发布"
        }


class FakeNotifier:
    _EVENTS = {
        "默认双渠道": "default_channels",
        "博客已上线": "blog_succeeded",
        "微信草稿已生成": "wechat_succeeded",
        "全部渠道已完成": "delivery_completed",
    }

    def __init__(self) -> None:
        self.events: list[str] = []
        self.calls: list[Notification] = []

    async def send(self, notification: Notification) -> None:
        self.calls.append(notification)
        event = self._EVENTS.get(notification.stage)
        if event is not None:
            self.events.append(event)
