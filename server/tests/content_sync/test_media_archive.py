import hashlib

import pytest
from reven.content_sync.domain import SyncStage
from reven.content_sync.executor import ContentSyncFailure
from reven.content_sync.media_archive import (
    ContentMediaArchive,
    DownloadedMedia,
)
from reven.integrations.notion.models import NotionFile
from reven.integrations.tencent_cos.store import ArchivedAsset, AssetArchiveError


class FakeDownloader:
    async def download(self, run_id, requests):  # type: ignore[no-untyped-def]
        del run_id
        for request in requests:
            yield _downloaded(request)


class FakeStore:
    def __init__(self) -> None:
        self.hashes: list[str] = []

    async def archive(self, content: bytes, *, sha256: str, mime_type: str) -> ArchivedAsset:
        assert hashlib.sha256(content).hexdigest() == sha256
        self.hashes.append(sha256)
        return ArchivedAsset(
            key=f"assets/sha256/{sha256[:2]}/{sha256}",
            sha256=sha256,
            mime_type=mime_type,
            size=len(content),
            public_url=f"https://assets.example/{sha256}",
            reused=False,
        )


@pytest.mark.anyio
async def test_archives_cover_and_markdown_media_then_rewrites_both_snapshot_forms() -> None:
    store = FakeStore()
    archive = ContentMediaArchive(FakeDownloader(), store)
    markdown = (
        "![图](https://files.notion.so/image.png?sig=secret)\n\n"
        "[附件](https://files.notion.so/report.pdf?sig=secret)\n\n"
        "[YouTube](https://youtube.com/watch?v=1)"
    )

    result = await archive.archive(
        "11111111-1111-1111-1111-111111111111",
        markdown,
        NotionFile("cover.png", "https://files.notion.so/cover.png?sig=secret"),
    )

    assert [item.kind for item in result.media] == ["封面", "图片", "附件"]
    assert len(store.hashes) == 3
    assert "files.notion.so" not in result.canonical_markdown
    assert "reven-asset://sha256/" in result.canonical_markdown
    assert "files.notion.so" not in result.portable_markdown
    assert "https://assets.example/" in result.portable_markdown
    assert "https://youtube.com/watch?v=1" in result.portable_markdown


@pytest.mark.anyio
async def test_reports_download_and_archive_progress_for_each_media() -> None:
    events: list[tuple[str, int, int, str | None]] = []

    async def progress(stage: str, current: int, total: int, media: str | None) -> None:
        events.append((stage, current, total, media))

    await ContentMediaArchive(FakeDownloader(), FakeStore()).archive(
        "11111111-1111-1111-1111-111111111111",
        "![图](https://files.notion.so/image.png)",
        NotionFile("cover.png", "https://files.notion.so/cover.png"),
        progress=progress,
    )

    assert events == [
        (SyncStage.DOWNLOADING_MEDIA, 1, 2, "cover.png"),
        (SyncStage.ARCHIVING_MEDIA, 1, 2, "cover.png"),
        (SyncStage.DOWNLOADING_MEDIA, 2, 2, "图"),
        (SyncStage.ARCHIVING_MEDIA, 2, 2, "图"),
    ]


@pytest.mark.anyio
async def test_object_address_conflict_is_a_permanent_sync_failure() -> None:
    events: list[tuple[str, int, int, str | None]] = []

    async def progress(stage: str, current: int, total: int, media: str | None) -> None:
        events.append((stage, current, total, media))

    class ConflictingStore:
        async def archive(self, content: bytes, *, sha256: str, mime_type: str) -> ArchivedAsset:
            del content, sha256, mime_type
            raise AssetArchiveError("object_conflict", "conflict")

    with pytest.raises(ContentSyncFailure) as captured:
        await ContentMediaArchive(FakeDownloader(), ConflictingStore()).archive(
            "11111111-1111-1111-1111-111111111111",
            "正文",
            NotionFile("cover.png", "https://files.notion.so/cover.png"),
            progress=progress,
        )

    assert captured.value.retryable is False
    assert events[-1] == (SyncStage.ARCHIVING_MEDIA, 1, 1, "cover.png")


@pytest.mark.anyio
async def test_reports_the_media_before_a_download_failure() -> None:
    events: list[tuple[str, int, int, str | None]] = []

    async def progress(stage: str, current: int, total: int, media: str | None) -> None:
        events.append((stage, current, total, media))

    class FailingDownloader:
        async def download(self, run_id, requests):  # type: ignore[no-untyped-def]
            del run_id, requests
            if False:
                yield
            raise ContentSyncFailure("MEDIA_DOWNLOAD_FAILED", "下载失败", media="cover.png")

    with pytest.raises(ContentSyncFailure):
        await ContentMediaArchive(FailingDownloader(), FakeStore()).archive(
            "11111111-1111-1111-1111-111111111111",
            "正文",
            NotionFile("cover.png", "https://files.notion.so/cover.png"),
            progress=progress,
        )

    assert events == [(SyncStage.DOWNLOADING_MEDIA, 1, 1, "cover.png")]


def _downloaded(request) -> DownloadedMedia:  # type: ignore[no-untyped-def]
    content = f"content:{request.ordinal}".encode()
    mime = "application/pdf" if request.kind == "附件" else "image/png"
    return DownloadedMedia(
        request=request,
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
        mime_type=mime,
        filename=request.label or None,
    )
