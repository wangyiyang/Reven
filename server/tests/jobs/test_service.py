import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import reven.jobs.service as service_module
from reven.articles.models import Article
from reven.domain import JobStatus
from reven.integrations.models import Integration
from reven.jobs.models import PublicationJob
from reven.jobs.repository import compute_target_channels_hash
from reven.jobs.service import NotionStatusWriteError, PublicationJobService
from reven.publishing.assets import AssetDownloadError, MaterializedAsset, MaterializedAssets
from reven.publishing.snapshot import build_snapshot
from sqlalchemy.ext.asyncio import async_sessionmaker


def test_target_channels_hash_is_order_independent() -> None:
    assert compute_target_channels_hash(["个人博客", "微信公众号"]) == compute_target_channels_hash(
        ["微信公众号", "个人博客"]
    )


def _page(*, cover: bool = True) -> dict[str, Any]:
    now = datetime.now(tz=UTC).isoformat()
    return {
        "id": "11111111-1111-1111-1111-111111111111",
        "url": "https://notion.so/page",
        "last_edited_time": now,
        "properties": {
            "标题": {"type": "title", "title": [{"plain_text": "标题"}]},
            "状态": {"type": "status", "status": {"name": "待发布"}},
            "目标渠道": {"type": "multi_select", "multi_select": [{"name": "个人博客"}]},
            "摘要": {"type": "rich_text", "rich_text": [{"plain_text": "摘要"}]},
            "封面": {
                "type": "files",
                "files": (
                    [{"type": "external", "name": "cover", "external": {"url": "https://example.com/cover.png"}}]
                    if cover
                    else []
                ),
            },
        },
    }


class FakeNotion:
    def __init__(self, page: dict[str, Any]) -> None:
        self.page = page
        self.updates: list[dict[str, Any]] = []

    async def retrieve_page(self, page_id: str) -> dict[str, Any]:
        del page_id
        return self.page

    async def retrieve_page_markdown(self, page_id: str) -> str:
        del page_id
        return "正文"

    async def update_page(self, page_id: str, *, properties: dict[str, Any]) -> dict[str, Any]:
        del page_id
        self.updates.append(properties)
        return {}


class FailingUpdateNotion(FakeNotion):
    async def update_page(self, page_id: str, *, properties: dict[str, Any]) -> dict[str, Any]:
        del page_id, properties
        raise RuntimeError("secret=https://signed.example/?token=sensitive")


class RecoveringUpdateNotion(FakeNotion):
    def __init__(self, page: dict[str, Any]) -> None:
        super().__init__(page)
        self.fail = True

    async def update_page(self, page_id: str, *, properties: dict[str, Any]) -> dict[str, Any]:
        if self.fail:
            raise RuntimeError("token=sensitive")
        return await super().update_page(page_id, properties=properties)


class FailingRetrieveNotion(FakeNotion):
    async def retrieve_page(self, page_id: str) -> dict[str, Any]:
        del page_id
        raise RuntimeError("token=sensitive")


class FakeMaterializer:
    def __init__(self) -> None:
        self.calls = 0

    async def materialize(self, job_id: str, image_urls: list[str], cover_url: str | None) -> MaterializedAssets:
        self.calls += 1
        del job_id, image_urls
        cover = (
            MaterializedAsset("cover", Path("/tmp/cover.png"), "b" * 64, "image/png", 10)
            if cover_url is not None
            else None
        )
        return MaterializedAssets((), cover)


class FailingBodyMaterializer(FakeMaterializer):
    async def materialize(self, job_id: str, image_urls: list[str], cover_url: str | None) -> MaterializedAssets:
        del job_id, image_urls
        assert cover_url is None
        raise AssetDownloadError("url_unsafe", "正文图片地址不安全", field="images")


class FilesystemFailingMaterializer(FakeMaterializer):
    async def materialize(self, job_id: str, image_urls: list[str], cover_url: str | None) -> MaterializedAssets:
        del job_id, image_urls, cover_url
        raise AssetDownloadError("filesystem_error", "素材文件写入失败", field="assets")


async def _seed_job(db_session) -> PublicationJob:  # type: ignore[no-untyped-def]
    now = datetime.now(tz=UTC)
    article = Article(
        notion_page_id="11111111-1111-1111-1111-111111111111",
        notion_url="https://notion.so/page",
        title="旧标题",
        notion_status="待发布",
        automation_status="等待中",
        target_channels=["个人博客"],
        notion_last_edited_at=now,
        last_synced_at=now,
    )
    db_session.add(article)
    db_session.add(
        Integration(
            provider="github",
            encrypted_secret="encrypted",
            connection_status="连接正常",
            last_tested_at=now,
        )
    )
    await db_session.flush()
    job = PublicationJob(
        article_id=article.id,
        content_hash=None,
        target_channels=["个人博客"],
        target_channels_hash=compute_target_channels_hash(["个人博客"]),
        overall_status=JobStatus.WAITING,
        blog_status="待处理",
        wechat_status="待处理",
        scheduled_at=now,
    )
    db_session.add(job)
    await db_session.commit()
    return job


@pytest.mark.anyio
async def test_prepare_freezes_latest_page_and_marks_processing(db_session) -> None:  # type: ignore[no-untyped-def]
    job = await _seed_job(db_session)
    notion = FakeNotion(_page())
    factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)

    result = await PublicationJobService(factory, notion, FakeMaterializer()).prepare(job.id)

    assert result.job_id == job.id
    assert result.reused is False
    await db_session.refresh(job)
    assert job.content_hash is not None
    assert job.source_markdown == "正文"
    assert job.overall_status == JobStatus.PROCESSING
    assert notion.updates[-1]["自动化状态"]["select"]["name"] == "处理中"


@pytest.mark.anyio
async def test_prepare_missing_cover_blocks_job_and_writes_reason(db_session) -> None:  # type: ignore[no-untyped-def]
    job = await _seed_job(db_session)
    notion = FakeNotion(_page(cover=False))
    factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)

    result = await PublicationJobService(factory, notion, FakeMaterializer()).prepare(job.id)

    assert result.blocked is True
    await db_session.refresh(job)
    assert job.overall_status == JobStatus.BLOCKED
    assert notion.updates[-1]["自动化状态"]["select"]["name"] == "阻塞"


@pytest.mark.anyio
async def test_processing_write_failure_keeps_frozen_pending_and_retry_only_writes_status(db_session) -> None:  # type: ignore[no-untyped-def]
    job = await _seed_job(db_session)
    notion = RecoveringUpdateNotion(_page())
    materializer = FakeMaterializer()
    factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)

    with pytest.raises(NotionStatusWriteError) as caught:
        await PublicationJobService(factory, notion, materializer).prepare(job.id)

    assert "sensitive" not in str(caught.value)
    await db_session.refresh(job)
    assert job.content_hash is not None
    assert job.overall_status == JobStatus.WAITING
    assert job.snapshot_metadata["notion_write_pending"] is True
    assert materializer.calls == 1

    notion.fail = False
    result = await PublicationJobService(factory, notion, materializer).prepare(job.id)

    assert result.job_id == job.id
    await db_session.refresh(job)
    assert job.overall_status == JobStatus.PROCESSING
    assert "notion_write_pending" not in job.snapshot_metadata
    assert materializer.calls == 1


@pytest.mark.anyio
async def test_retry_repeats_idempotent_notion_write_after_second_transaction_crash(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    job = await _seed_job(db_session)
    notion = FakeNotion(_page())
    materializer = FakeMaterializer()
    factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    service = PublicationJobService(factory, notion, materializer)
    original_mark = service._mark_processing

    async def crash(job_id: Any) -> None:
        del job_id
        raise RuntimeError("simulated process crash")

    monkeypatch.setattr(service, "_mark_processing", crash)
    with pytest.raises(RuntimeError, match="simulated"):
        await service.prepare(job.id)
    await db_session.refresh(job)
    assert job.snapshot_metadata["notion_write_pending"] is True
    assert len(notion.updates) == 1

    monkeypatch.setattr(service, "_mark_processing", original_mark)
    await service.prepare(job.id)
    await db_session.refresh(job)
    assert job.overall_status == JobStatus.PROCESSING
    assert len(notion.updates) == 2
    assert materializer.calls == 1


@pytest.mark.anyio
async def test_blocked_write_failure_keeps_local_blocked(db_session) -> None:  # type: ignore[no-untyped-def]
    job = await _seed_job(db_session)
    notion = FailingUpdateNotion(_page(cover=False))
    factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)

    with pytest.raises(NotionStatusWriteError) as caught:
        await PublicationJobService(factory, notion, FakeMaterializer()).prepare(job.id)

    assert "sensitive" not in str(caught.value)
    await db_session.refresh(job)
    assert job.content_hash is None
    assert job.overall_status == JobStatus.BLOCKED


@pytest.mark.anyio
async def test_missing_cover_still_reports_body_materialization_failure(db_session) -> None:  # type: ignore[no-untyped-def]
    job = await _seed_job(db_session)
    notion = FakeNotion(_page(cover=False))
    notion.retrieve_page_markdown = lambda page_id: _async_value("![坏图](https://127.0.0.1/a.png)")  # type: ignore[method-assign]
    factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)

    result = await PublicationJobService(factory, notion, FailingBodyMaterializer()).prepare(job.id)

    assert result.validation is not None
    assert {error.code for error in result.validation.errors} >= {"cover_missing", "url_unsafe"}


@pytest.mark.anyio
async def test_filesystem_failure_persists_blocked_job(db_session) -> None:  # type: ignore[no-untyped-def]
    job = await _seed_job(db_session)
    factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)

    result = await PublicationJobService(factory, FakeNotion(_page()), FilesystemFailingMaterializer()).prepare(job.id)

    assert result.validation is not None
    assert "filesystem_error" in {error.code for error in result.validation.errors}
    await db_session.refresh(job)
    assert job.overall_status == JobStatus.BLOCKED


async def _async_value(value: str) -> str:
    return value


@pytest.mark.anyio
async def test_prepare_reuses_existing_frozen_job(db_session) -> None:  # type: ignore[no-untyped-def]
    current = await _seed_job(db_session)
    snapshot = build_snapshot(
        "正文",
        image_sha256=(),
        cover_sha256="b" * 64,
        title="标题",
        summary="摘要",
    )
    existing = PublicationJob(
        article_id=current.article_id,
        content_hash=snapshot.content_hash,
        target_channels=["个人博客"],
        target_channels_hash=compute_target_channels_hash(["个人博客"]),
        source_markdown=snapshot.markdown,
        overall_status=JobStatus.COMPLETED,
        blog_status="已上线",
        wechat_status="待处理",
        scheduled_at=datetime.now(tz=UTC),
    )
    db_session.add(existing)
    await db_session.commit()
    notion = FakeNotion(_page())
    factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)

    result = await PublicationJobService(factory, notion, FakeMaterializer()).prepare(current.id)

    assert result.job_id == existing.id
    assert result.reused is True
    await db_session.refresh(current)
    assert current.overall_status == JobStatus.CANCELLED


@pytest.mark.anyio
async def test_source_refresh_failure_blocks_with_redacted_reason(db_session) -> None:  # type: ignore[no-untyped-def]
    job = await _seed_job(db_session)
    notion = FailingRetrieveNotion(_page())
    factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)

    result = await PublicationJobService(factory, notion, FakeMaterializer()).prepare(job.id)

    assert result.blocked is True
    await db_session.refresh(job)
    assert job.overall_status == JobStatus.BLOCKED
    assert "sensitive" not in str(result.validation)


@pytest.mark.anyio
async def test_concurrent_prepare_returns_single_frozen_winner(db_session, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    first = await _seed_job(db_session)
    second = PublicationJob(
        article_id=first.article_id,
        content_hash=None,
        target_channels=["个人博客"],
        target_channels_hash=compute_target_channels_hash(["个人博客"]),
        overall_status=JobStatus.FAILED,
        blog_status="待处理",
        wechat_status="待处理",
        scheduled_at=datetime.now(tz=UTC),
    )
    db_session.add(second)
    await db_session.commit()
    factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    notion = FakeNotion(_page())
    original_lookup = service_module._existing_frozen
    ready = asyncio.Event()
    lookup_count = 0

    async def synchronized_lookup(*args: Any, **kwargs: Any) -> PublicationJob | None:
        nonlocal lookup_count
        with args[0].no_autoflush:
            result = await original_lookup(*args, **kwargs)
        lookup_count += 1
        if lookup_count < 2:
            await ready.wait()
        else:
            ready.set()
        return result

    monkeypatch.setattr(service_module, "_existing_frozen", synchronized_lookup)

    first_result, second_result = await asyncio.gather(
        PublicationJobService(factory, notion, FakeMaterializer()).prepare(first.id),
        PublicationJobService(factory, notion, FakeMaterializer()).prepare(second.id),
    )

    assert first_result.job_id == second_result.job_id
    assert first_result.reused != second_result.reused
    await db_session.refresh(first)
    await db_session.refresh(second)
    assert {first.overall_status, second.overall_status} == {JobStatus.PROCESSING, JobStatus.CANCELLED}


@pytest.mark.anyio
async def test_non_target_integrity_error_is_not_treated_as_idempotency(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    job = await _seed_job(db_session)
    original_freeze = service_module._freeze

    def corrupt_foreign_key(*args: Any, **kwargs: Any) -> None:
        original_freeze(*args, **kwargs)
        args[0].article_id = uuid4()

    monkeypatch.setattr(service_module, "_freeze", corrupt_foreign_key)
    factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)

    with pytest.raises(Exception) as caught:
        await PublicationJobService(factory, FakeNotion(_page()), FakeMaterializer()).prepare(job.id)

    assert type(caught.value).__name__ == "IntegrityError"


@pytest.mark.anyio
async def test_unmappable_parser_image_blocks_instead_of_silently_dropping(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    job = await _seed_job(db_session)

    def fail_snapshot(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("source positions unavailable")

    monkeypatch.setattr(service_module, "build_snapshot", fail_snapshot)
    factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)

    result = await PublicationJobService(factory, FakeNotion(_page()), FakeMaterializer()).prepare(job.id)

    assert result.validation is not None
    assert {error.code for error in result.validation.errors} == {"snapshot_conversion_failed"}
    await db_session.refresh(job)
    assert job.overall_status == JobStatus.BLOCKED
