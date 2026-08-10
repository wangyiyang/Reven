from datetime import UTC, datetime
from uuid import uuid4

import pytest
from reven.articles.models import Article
from reven.content_sync.domain import ContentSyncStatus, SyncRunStatus, SyncStage
from reven.content_sync.gate import CurrentSnapshotGate, SnapshotUnavailableError
from reven.content_sync.models import ContentSnapshot, ContentSyncRun, SnapshotAsset
from sqlalchemy.ext.asyncio import async_sessionmaker


class FakeVersionSource:
    def __init__(self, version: datetime) -> None:
        self.version = version

    async def current_version(self, page_id: str) -> datetime:
        assert page_id
        return self.version


class FailingVerifier:
    async def verify(self, assets):  # type: ignore[no-untyped-def]
        assert assets
        raise RuntimeError("COS unavailable")


@pytest.mark.anyio
async def test_gate_returns_current_snapshot_when_notion_version_matches(db_session) -> None:  # type: ignore[no-untyped-def]
    version = datetime.now(tz=UTC)
    article, run, snapshot, asset = _snapshot_graph(version)
    db_session.add_all([article, run])
    await db_session.flush()
    db_session.add(snapshot)
    await db_session.flush()
    db_session.add(asset)
    article.current_snapshot_id = snapshot.id
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    current = await CurrentSnapshotGate(factory, FakeVersionSource(version)).require(article.id)

    assert current.id == snapshot.id
    assert current.portable_markdown == "# 标题\n\n正文\n"
    assert current.assets[0].sha256 == "c" * 64


@pytest.mark.anyio
async def test_gate_marks_snapshot_stale_when_notion_version_changes(db_session) -> None:  # type: ignore[no-untyped-def]
    version = datetime.now(tz=UTC)
    article, run, snapshot, asset = _snapshot_graph(version)
    await _persist_graph(db_session, article, run, snapshot, asset)
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    with pytest.raises(SnapshotUnavailableError) as captured:
        await CurrentSnapshotGate(factory, FakeVersionSource(datetime(2026, 8, 11, tzinfo=UTC))).require(article.id)

    async with factory() as session:
        persisted = await session.get(Article, article.id)
    assert captured.value.code == "SNAPSHOT_STALE"
    assert persisted is not None
    assert persisted.content_sync_status == ContentSyncStatus.STALE
    assert persisted.current_snapshot_id == snapshot.id


@pytest.mark.anyio
async def test_gate_fails_closed_when_archived_asset_cannot_be_verified(db_session) -> None:  # type: ignore[no-untyped-def]
    version = datetime.now(tz=UTC)
    article, run, snapshot, asset = _snapshot_graph(version)
    await _persist_graph(db_session, article, run, snapshot, asset)
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    with pytest.raises(SnapshotUnavailableError) as captured:
        await CurrentSnapshotGate(factory, FakeVersionSource(version), FailingVerifier()).require(article.id)

    async with factory() as session:
        persisted = await session.get(Article, article.id)
    assert captured.value.code == "SNAPSHOT_ASSET_UNAVAILABLE"
    assert persisted is not None
    assert persisted.content_sync_status == ContentSyncStatus.FAILED
    assert persisted.current_snapshot_id == snapshot.id


async def _persist_graph(db_session, article, run, snapshot, asset) -> None:  # type: ignore[no-untyped-def]
    db_session.add_all([article, run])
    await db_session.flush()
    db_session.add(snapshot)
    await db_session.flush()
    db_session.add(asset)
    article.current_snapshot_id = snapshot.id
    await db_session.commit()


def _snapshot_graph(version: datetime) -> tuple[Article, ContentSyncRun, ContentSnapshot, SnapshotAsset]:
    article_id = uuid4()
    run_id = uuid4()
    snapshot_id = uuid4()
    article = Article(
        id=article_id,
        notion_page_id=str(uuid4()),
        notion_url="https://www.notion.so/page",
        title="标题",
        notion_status="待发布",
        automation_status="未开始",
        notion_last_edited_at=version,
        last_synced_at=version,
        content_sync_status=ContentSyncStatus.SYNCED,
    )
    run = ContentSyncRun(
        id=run_id,
        article_id=article_id,
        status=SyncRunStatus.SUCCEEDED,
        stage=SyncStage.COMPLETED,
        source_last_edited_at=version,
        next_attempt_at=version,
        finished_at=version,
    )
    snapshot = ContentSnapshot(
        id=snapshot_id,
        article_id=article_id,
        sync_run_id=run_id,
        source_last_edited_at=version,
        title="标题",
        source_markdown="正文",
        portable_markdown="# 标题\n\n正文\n",
        content_hash="a" * 64,
        synced_at=version,
        created_at=version,
    )
    asset = SnapshotAsset(
        snapshot_id=snapshot_id,
        ordinal=0,
        kind="封面",
        embedded=False,
        source_url="https://files.notion.so/cover.png",
        storage_key="assets/sha256/cc/cover",
        public_url="https://assets.example/cover",
        sha256="c" * 64,
        mime_type="image/png",
        byte_size=7,
        created_at=version,
    )
    return article, run, snapshot, asset
