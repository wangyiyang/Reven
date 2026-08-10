"""SSRF-safe, bounded downloader for snapshot images, media, and attachments."""

import hashlib
import ipaddress
import os
import shutil
import socket
from collections.abc import AsyncIterator
from pathlib import Path
from typing import cast
from urllib.parse import unquote, urljoin, urlsplit
from uuid import UUID

import httpcore
import httpx

from reven.content_sync.executor import ContentSyncFailure
from reven.content_sync.media_archive import DownloadedMedia, DownloadRequest
from reven.publishing.assets import HttpcorePinnedRequester, PinnedRequester, Resolver, default_resolver

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_OTHER_BYTES = 50 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 200 * 1024 * 1024
MAX_REDIRECTS = 5

_IMAGE_MAGIC: dict[str, tuple[bytes, ...]] = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/gif": (b"GIF87a", b"GIF89a"),
    "image/webp": (b"RIFF",),
}
_ATTACHMENT_MAGIC: dict[str, tuple[bytes, ...]] = {
    "application/pdf": (b"%PDF-",),
    "application/zip": (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (b"PK\x03\x04",),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": (b"PK\x03\x04",),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": (b"PK\x03\x04",),
}
_AUDIO_MAGIC: dict[str, tuple[bytes, ...]] = {
    "audio/mpeg": (b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"),
    "audio/ogg": (b"OggS",),
    "audio/wav": (b"RIFF",),
    "audio/flac": (b"fLaC",),
    "audio/mp4": (b"ftyp",),
}
_VIDEO_MAGIC: dict[str, tuple[bytes, ...]] = {
    "video/mp4": (b"ftyp",),
    "video/quicktime": (b"ftyp",),
    "video/webm": (b"\x1aE\xdf\xa3",),
}


class SecureContentDownloader:
    def __init__(
        self,
        data_root: Path,
        *,
        requester: PinnedRequester | None = None,
        resolver: Resolver = default_resolver,
    ) -> None:
        self.data_root = data_root
        self.requester = requester or HttpcorePinnedRequester()
        self.resolver = resolver

    async def download(
        self,
        run_id: UUID | str,
        requests: tuple[DownloadRequest, ...],
    ) -> AsyncIterator[DownloadedMedia]:
        directory = self._directory(run_id)
        total = 0
        try:
            for request in requests:
                downloaded = await self._download(request, directory, total)
                total += len(downloaded.content)
                yield downloaded
        finally:
            shutil.rmtree(directory, ignore_errors=True)
            _remove_empty(directory.parent, self.data_root)

    async def _download(self, request: DownloadRequest, directory: Path, total: int) -> DownloadedMedia:
        current = request.source_url
        try:
            for redirect in range(MAX_REDIRECTS + 1):
                pinned_ip = await self._validated_ip(current, request.label)
                async with self.requester.stream(current, pinned_ip) as response:
                    if response.is_redirect:
                        current = _redirect_target(response, current, redirect, request.label)
                        continue
                    if not response.is_success:
                        raise ContentSyncFailure(
                            "MEDIA_DOWNLOAD_FAILED",
                            "媒体下载失败，请稍后重试",
                            retryable=True,
                            media=request.label,
                        )
                    return await self._save(response, request, directory, total)
        except ContentSyncFailure:
            raise
        except (httpx.HTTPError, httpcore.NetworkError, httpcore.ProtocolError, httpcore.TimeoutException) as exc:
            raise ContentSyncFailure(
                "MEDIA_DOWNLOAD_FAILED",
                "媒体网络请求失败，请稍后重试",
                retryable=True,
                media=request.label,
            ) from exc
        raise ContentSyncFailure("MEDIA_REDIRECT_LIMIT", "媒体重定向次数过多", media=request.label)

    async def _validated_ip(self, url: str, label: str) -> str:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ContentSyncFailure("MEDIA_URL_UNSAFE", "媒体地址不安全：仅允许 HTTPS", media=label)
        try:
            addresses = await self.resolver(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
        except (OSError, ValueError) as exc:
            raise ContentSyncFailure(
                "MEDIA_DNS_FAILED",
                "媒体域名解析失败，请稍后重试",
                retryable=True,
                media=label,
            ) from exc
        ips = [str(item[-1][0]) for item in addresses if item and isinstance(item[-1], tuple)]
        if not ips or any(_unsafe_ip(item) for item in ips):
            raise ContentSyncFailure("MEDIA_URL_UNSAFE", "媒体地址不安全：禁止访问内部网络", media=label)
        return ips[0]

    async def _save(
        self,
        response: httpx.Response,
        request: DownloadRequest,
        directory: Path,
        snapshot_bytes: int,
    ) -> DownloadedMedia:
        declared = response.headers.get("content-type", "").split(";", 1)[0].strip().casefold()
        path = directory / f"{request.ordinal:04d}.part"
        size, digest, header = await _stream_to_file(response, path, request, snapshot_bytes)
        _validate_format(declared, header, request)
        content = path.read_bytes()
        if len(content) != size:
            raise ContentSyncFailure("MEDIA_READ_FAILED", "媒体临时文件读取不完整", media=request.label)
        return DownloadedMedia(
            request=request,
            content=content,
            sha256=digest,
            mime_type=declared,
            filename=_filename(request),
        )

    def _directory(self, run_id: UUID | str) -> Path:
        try:
            normalized = str(UUID(str(run_id)))
        except ValueError as exc:
            raise ContentSyncFailure("SYNC_RUN_INVALID", "同步任务标识无效") from exc
        if self.data_root.is_symlink():
            raise ContentSyncFailure("MEDIA_FILESYSTEM_UNSAFE", "媒体目录不能是符号链接")
        root = self.data_root.resolve()
        directory = root / "content-sync" / normalized
        directory.mkdir(parents=True, exist_ok=False)
        if not directory.resolve().is_relative_to(root):
            raise ContentSyncFailure("MEDIA_FILESYSTEM_UNSAFE", "媒体临时目录越界")
        return directory


async def _stream_to_file(
    response: httpx.Response,
    path: Path,
    request: DownloadRequest,
    snapshot_bytes: int,
) -> tuple[int, str, bytes]:
    limit = MAX_IMAGE_BYTES if request.kind in {"封面", "图片"} else MAX_OTHER_BYTES
    size = 0
    digest = hashlib.sha256()
    header = b""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > limit or snapshot_bytes + size > MAX_SNAPSHOT_BYTES:
                    raise ContentSyncFailure("MEDIA_TOO_LARGE", "媒体超过大小限制", media=request.label)
                header = (header + chunk)[:32]
                digest.update(chunk)
                output.write(chunk)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return size, digest.hexdigest(), header


def _validate_format(declared: str, header: bytes, request: DownloadRequest) -> None:
    allowed = _allowed_magic(request.kind)
    signatures = allowed.get(declared)
    valid = signatures is not None and any(_matches_signature(declared, header, item) for item in signatures)
    if declared == "text/plain":
        valid = request.kind == "附件" and b"\x00" not in header
    if not valid:
        raise ContentSyncFailure(
            "MEDIA_FORMAT_INVALID",
            "媒体 MIME 与真实文件格式不一致或类型不受支持",
            media=request.label,
        )


def _allowed_magic(kind: str) -> dict[str, tuple[bytes, ...]]:
    if kind in {"封面", "图片"}:
        return _IMAGE_MAGIC
    if kind == "音频":
        return _AUDIO_MAGIC
    if kind == "视频":
        return _VIDEO_MAGIC
    return {**_ATTACHMENT_MAGIC, "text/plain": ()}


def _matches_signature(mime: str, header: bytes, signature: bytes) -> bool:
    if mime in {"image/webp", "audio/wav"}:
        suffix = b"WEBP" if mime == "image/webp" else b"WAVE"
        return header.startswith(signature) and header[8:12] == suffix
    if mime in {"audio/mp4", "video/mp4", "video/quicktime"}:
        return header[4:8] == signature
    return header.startswith(signature)


def _redirect_target(response: httpx.Response, current: str, redirect: int, label: str) -> str:
    if redirect == MAX_REDIRECTS:
        raise ContentSyncFailure("MEDIA_REDIRECT_LIMIT", "媒体重定向次数过多", media=label)
    location = response.headers.get("location")
    if not location:
        raise ContentSyncFailure("MEDIA_REDIRECT_INVALID", "媒体重定向地址无效", media=label)
    return cast(str, urljoin(current, location))


def _unsafe_ip(raw: str) -> bool:
    try:
        address = ipaddress.ip_address(raw.split("%", 1)[0])
    except ValueError:
        return True
    return not address.is_global


def _filename(request: DownloadRequest) -> str:
    candidate = Path(request.label).name or Path(unquote(urlsplit(request.source_url).path)).name
    return candidate[:255] or f"media-{request.ordinal}"


def _remove_empty(directory: Path, stop: Path) -> None:
    while directory != stop and directory.is_relative_to(stop):
        try:
            directory.rmdir()
        except OSError:
            return
        directory = directory.parent
