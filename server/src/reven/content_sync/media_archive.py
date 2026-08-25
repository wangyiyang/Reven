"""Archive every snapshot media object and produce stable Markdown forms."""

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from reven.content_sync.domain import SyncStage
from reven.content_sync.executor import ArchivedContent, ArchivedMedia, ContentSyncFailure
from reven.content_sync.markdown_media import MarkdownMedia, discover_media, rewrite_media
from reven.integrations.notion.models import NotionFile
from reven.integrations.tencent_cos.client import TencentCosRequestError
from reven.integrations.tencent_cos.store import ArchivedAsset, AssetArchiveError


@dataclass(frozen=True)
class DownloadRequest:
    ordinal: int
    kind: str
    embedded: bool
    source_url: str
    label: str


@dataclass(frozen=True)
class DownloadedMedia:
    request: DownloadRequest
    content: bytes
    sha256: str
    mime_type: str
    filename: str | None = None


class MediaDownloader(Protocol):
    def download(
        self,
        run_id: UUID | str,
        requests: tuple[DownloadRequest, ...],
    ) -> AsyncIterator[DownloadedMedia]: ...


class ContentAssetStore(Protocol):
    async def archive(self, content: bytes, *, sha256: str, mime_type: str) -> ArchivedAsset: ...


MediaProgress = Callable[[str, int, int, str | None], Awaitable[None]]


class ContentMediaArchive:
    def __init__(self, downloader: MediaDownloader, store: ContentAssetStore) -> None:
        self.downloader = downloader
        self.store = store

    async def archive(
        self,
        run_id: UUID | str,
        markdown: str,
        cover: NotionFile | None,
        *,
        progress: MediaProgress | None = None,
    ) -> ArchivedContent:
        # 封面在同步期可选：缺封面只影响发布（发布校验与快照准备双层兜底），
        # 不应阻塞内容快照本身（预览/复制 Markdown 不依赖封面）。
        manifest = discover_media(markdown)
        requests = (
            *([_cover_request(cover)] if cover is not None else []),
            *(_media_request(item) for item in manifest),
        )
        archived = await self._download_and_archive(run_id, requests, progress)
        body_assets = archived[1:] if cover is not None else archived
        canonical = rewrite_media(
            markdown,
            manifest,
            tuple(f"reven-asset://sha256/{item[0].sha256}" for item in body_assets),
        )
        portable = rewrite_media(markdown, manifest, tuple(item[0].public_url for item in body_assets))
        media = tuple(_archived_media(requests[index], item[0], item[1]) for index, item in enumerate(archived))
        return ArchivedContent(canonical, portable, media)

    async def _download_and_archive(
        self,
        run_id: UUID | str,
        requests: tuple[DownloadRequest, ...],
        progress: MediaProgress | None,
    ) -> list[tuple[ArchivedAsset, str | None]]:
        results: list[tuple[ArchivedAsset, str | None]] = []
        if progress is not None and requests:
            await progress(SyncStage.DOWNLOADING_MEDIA, 1, len(requests), requests[0].label)
        async for item in self.downloader.download(run_id, requests):
            index = len(results)
            if index >= len(requests) or item.request != requests[index]:
                raise ContentSyncFailure("MEDIA_MANIFEST_MISMATCH", "媒体下载结果与清单不一致")
            current = index + 1
            if progress is not None:
                await progress(SyncStage.ARCHIVING_MEDIA, current, len(requests), item.request.label)
            archived = await self._archive(item)
            results.append((archived, item.filename))
            if progress is not None and current < len(requests):
                await progress(
                    SyncStage.DOWNLOADING_MEDIA,
                    current + 1,
                    len(requests),
                    requests[current].label,
                )
        if len(results) != len(requests):
            raise ContentSyncFailure("MEDIA_MANIFEST_MISMATCH", "媒体下载结果与清单不一致")
        return results

    async def _archive(self, item: DownloadedMedia) -> ArchivedAsset:
        try:
            return await self.store.archive(item.content, sha256=item.sha256, mime_type=item.mime_type)
        except TencentCosRequestError as exc:
            raise ContentSyncFailure(
                f"COS_{exc.code.upper()}",
                "对象存储请求失败，请稍后重试" if exc.retryable else "对象存储配置或权限错误",
                retryable=exc.retryable,
                media=item.request.label,
            ) from exc
        except AssetArchiveError as exc:
            raise ContentSyncFailure(
                f"COS_{exc.code.upper()}",
                "对象存储归档校验失败",
                retryable=False,
                media=item.request.label,
            ) from exc


def _cover_request(cover: NotionFile) -> DownloadRequest:
    return DownloadRequest(0, "封面", False, cover.url, cover.name or "封面")


def _media_request(item: MarkdownMedia) -> DownloadRequest:
    return DownloadRequest(item.ordinal, item.kind, item.embedded, item.source_url, item.label)


def _archived_media(request: DownloadRequest, archived: ArchivedAsset, filename: str | None) -> ArchivedMedia:
    return ArchivedMedia(
        ordinal=request.ordinal,
        kind=request.kind,
        embedded=request.embedded,
        source_url=_safe_source_url(request.source_url),
        storage_key=archived.key,
        public_url=archived.public_url,
        sha256=archived.sha256,
        mime_type=archived.mime_type,
        byte_size=archived.size,
        filename=filename,
        alt_text=request.label if request.kind == "图片" else None,
    )


def _safe_source_url(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
