from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

import httpx
import pytest
from reven.articles.models import Article
from reven.content_sync.domain import ContentSyncStatus, SyncRunStatus, SyncStage
from reven.content_sync.gate import CurrentSnapshotView, SnapshotAssetView
from reven.content_sync.models import ContentSnapshot, ContentSyncRun
from reven.content_sync.publication import (
    PreparedPublicationSnapshot,
    SnapshotPublicationMaterializer,
    SnapshotPublicationPreparationService,
)
from reven.domain import AutomationStatus
from reven.jobs.models import PublicationJob
from reven.jobs.repository import JobRepository, compute_target_channels_hash
from sqlalchemy.ext.asyncio import async_sessionmaker


class FakeGate:
    def __init__(self, current: CurrentSnapshotView) -> None:
        self.current = current
        self.calls = []

    async def require(self, article_id):  # type: ignore[no-untyped-def]
        self.calls.append(article_id)
        return self.current


class FakeMaterializer:
    def __init__(self) -> None:
        self.calls = []

    async def materialize(self, job_id, snapshot):  # type: ignore[no-untyped-def]
        self.calls.append((job_id, snapshot.id))
        return PreparedPublicationSnapshot(
            source_markdown="正文 ![图](https://assets.example/image.png)",
            metadata={
                "title": "标题",
                "summary": "摘要",
                "categories": ["工程"],
                "images": [],
                "cover": {"path": "/data/cover.png", "sha256": "c" * 64},
                "cover_sha256": "c" * 64,
            },
        )


@pytest.mark.anyio
async def test_preparation_pins_current_snapshot_without_reading_notion_body(db_session) -> None:  # type: ignore[no-untyped-def]
    now = datetime.now(tz=UTC)
    article, run, snapshot, job = _graph(now)
    db_session.add_all([article, run])
    await db_session.flush()
    db_session.add(snapshot)
    await db_session.flush()
    article.current_snapshot_id = snapshot.id
    db_session.add(job)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    async with factory.begin() as session:
        claim = await JobRepository(session).claim_next(lease_seconds=120)
    assert claim is not None
    current = CurrentSnapshotView(
        snapshot.id,
        article.id,
        now,
        now,
        "标题",
        "正文 reven-asset://sha256/hash",
        "# 标题\n\n正文",
        snapshot.content_hash,
        snapshot.snapshot_metadata,
        (),
    )
    gate = FakeGate(current)
    materializer = FakeMaterializer()

    await SnapshotPublicationPreparationService(factory, gate, materializer).prepare_claim(claim)

    async with factory() as session:
        persisted = await session.get(PublicationJob, job.id)
        persisted_article = await session.get(Article, article.id)
    assert persisted is not None
    assert persisted.snapshot_id == snapshot.id
    assert persisted.content_hash == snapshot.content_hash
    assert persisted.source_markdown.startswith("正文")
    assert persisted.snapshot_metadata["title"] == "标题"
    assert persisted_article is not None
    assert persisted_article.automation_status == AutomationStatus.PROCESSING
    assert gate.calls == [article.id]
    assert materializer.calls == [(job.id, snapshot.id)]


def _graph(now: datetime) -> tuple[Article, ContentSyncRun, ContentSnapshot, PublicationJob]:
    article_id = uuid4()
    run_id = uuid4()
    snapshot_id = uuid4()
    article = Article(
        id=article_id,
        notion_page_id=str(uuid4()),
        notion_url="https://www.notion.so/page",
        title="标题",
        notion_status="待发布",
        automation_status=AutomationStatus.WAITING,
        target_channels=["个人博客"],
        notion_last_edited_at=now,
        last_synced_at=now,
        content_sync_status=ContentSyncStatus.SYNCED,
    )
    run = ContentSyncRun(
        id=run_id,
        article_id=article_id,
        status=SyncRunStatus.SUCCEEDED,
        stage=SyncStage.COMPLETED,
        next_attempt_at=now,
    )
    snapshot = ContentSnapshot(
        id=snapshot_id,
        article_id=article_id,
        sync_run_id=run_id,
        source_last_edited_at=now,
        title="标题",
        source_markdown="正文",
        portable_markdown="# 标题\n\n正文",
        content_hash="a" * 64,
        snapshot_metadata={"summary": "摘要", "categories": ["工程"]},
    )
    job = PublicationJob(
        id=uuid4(),
        article_id=article_id,
        target_channels=["个人博客"],
        target_channels_hash=compute_target_channels_hash(["个人博客"]),
        overall_status="等待中",
        blog_status="待处理",
        wechat_status="待处理",
        scheduled_at=now,
    )
    return article, run, snapshot, job


@pytest.mark.anyio
async def test_materializer_reads_and_verifies_cos_assets_into_one_job_snapshot(tmp_path) -> None:  # type: ignore[no-untyped-def]
    cover = b"cover"
    image = b"image"
    attachment = b"attachment"
    content_by_path = {
        "/assets/cover": (cover, "image/png"),
        "/assets/image": (image, "image/png"),
        "/assets/report": (attachment, "application/pdf"),
    }

    def respond(request: httpx.Request) -> httpx.Response:
        content, mime_type = content_by_path[request.url.path]
        return httpx.Response(200, content=content, headers={"content-type": mime_type})

    snapshot_id = uuid4()
    article_id = uuid4()
    snapshot = CurrentSnapshotView(
        snapshot_id,
        article_id,
        datetime.now(tz=UTC),
        datetime.now(tz=UTC),
        "标题",
        (
            f"![图](reven-asset://sha256/{sha256(image).hexdigest()}) "
            f"[附件](reven-asset://sha256/{sha256(attachment).hexdigest()})"
        ),
        "# 标题",
        "a" * 64,
        {"summary": "摘要", "categories": ["工程"]},
        (
            _asset(0, "封面", False, "cover", cover, "image/png"),
            _asset(1, "图片", True, "image", image, "image/png"),
            _asset(2, "附件", False, "report", attachment, "application/pdf"),
        ),
    )
    materializer = SnapshotPublicationMaterializer(
        tmp_path,
        "https://assets.example",
        transport=httpx.MockTransport(respond),
    )

    prepared = await materializer.materialize(uuid4(), snapshot)

    assert "reven-asset://" not in prepared.source_markdown
    assert "https://assets.example/assets/report" in prepared.source_markdown
    assert len(prepared.metadata["images"]) == 1
    assert prepared.metadata["cover_sha256"] == sha256(cover).hexdigest()
    assert len(list((tmp_path / "jobs").glob("*/snapshot/*"))) == 3


def _asset(
    ordinal: int,
    kind: str,
    embedded: bool,
    name: str,
    content: bytes,
    mime_type: str,
) -> SnapshotAssetView:
    digest = sha256(content).hexdigest()
    return SnapshotAssetView(
        ordinal=ordinal,
        kind=kind,
        embedded=embedded,
        storage_key=f"assets/{name}",
        public_url=f"https://assets.example/assets/{name}",
        sha256=digest,
        mime_type=mime_type,
        byte_size=len(content),
        filename=f"{name}.bin",
        alt_text=name,
    )
