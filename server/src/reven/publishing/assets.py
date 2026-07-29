"""Secure, bounded materialization of remote publication images."""

import hashlib
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from urllib.parse import urljoin, urlsplit

import httpx

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_JOB_BYTES = 50 * 1024 * 1024
MAX_REDIRECTS = 5
Resolver = Callable[..., Awaitable[list[tuple[Any, ...]]]]

_MAGIC: tuple[tuple[str, str, bytes], ...] = (
    ("image/png", ".png", b"\x89PNG\r\n\x1a\n"),
    ("image/jpeg", ".jpg", b"\xff\xd8\xff"),
    ("image/gif", ".gif", b"GIF8"),
    ("image/webp", ".webp", b"RIFF"),
)


class AssetDownloadError(Exception):
    def __init__(self, code: str, message: str, *, field: str) -> None:
        super().__init__(message)
        self.code = code
        self.field = field


@dataclass(frozen=True)
class MaterializedAsset:
    original_url: str
    path: Path
    sha256: str
    mime_type: str
    size: int


@dataclass(frozen=True)
class MaterializedAssets:
    images: tuple[MaterializedAsset, ...]
    cover: MaterializedAsset


async def default_resolver(host: str, port: int, *, type: int) -> list[tuple[Any, ...]]:
    loop = __import__("asyncio").get_running_loop()
    result = await loop.getaddrinfo(host, port, type=type)
    return cast(list[tuple[Any, ...]], result)


class AssetMaterializer:
    def __init__(self, data_root: Path, http: httpx.AsyncClient, *, resolver: Resolver = default_resolver) -> None:
        self.data_root = data_root
        self.http = http
        self.resolver = resolver

    async def materialize(self, job_id: str, image_urls: list[str], cover_url: str) -> MaterializedAssets:
        directory = self.data_root / "jobs" / job_id / "snapshot"
        directory.mkdir(parents=True, exist_ok=True)
        total = 0
        images: list[MaterializedAsset] = []
        try:
            for ordinal, url in enumerate(image_urls, start=1):
                asset = await self._download(url, directory, f"image-{ordinal}", "images", total)
                total += asset.size
                images.append(asset)
            cover = await self._download(cover_url, directory, "cover", "cover", total)
            return MaterializedAssets(tuple(images), cover)
        except Exception:
            for path in directory.glob("*"):
                if path.is_file():
                    path.unlink()
            raise

    async def _download(self, url: str, directory: Path, stem: str, field: str, job_bytes: int) -> MaterializedAsset:
        try:
            return await self._download_checked(url, directory, stem, field, job_bytes)
        except httpx.HTTPError as exc:
            raise AssetDownloadError("download_failed", "素材网络请求失败，请稍后重试", field=field) from exc

    async def _download_checked(
        self, url: str, directory: Path, stem: str, field: str, job_bytes: int
    ) -> MaterializedAsset:
        current = url
        for redirect in range(MAX_REDIRECTS + 1):
            await self._validate_url(current, field)
            async with self.http.stream("GET", current, follow_redirects=False) as response:
                if response.is_redirect:
                    if redirect == MAX_REDIRECTS:
                        raise AssetDownloadError("redirect_limit", "素材重定向次数过多", field=field)
                    location = response.headers.get("location")
                    if not location:
                        raise AssetDownloadError("redirect_invalid", "素材重定向地址无效", field=field)
                    current = urljoin(current, location)
                    continue
                if not response.is_success:
                    raise AssetDownloadError("download_failed", "素材下载失败", field=field)
                return await self._save_response(response, url, directory, stem, field, job_bytes)
        raise AssetDownloadError("redirect_limit", "素材重定向次数过多", field=field)

    async def _validate_url(self, url: str, field: str) -> None:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise AssetDownloadError("url_unsafe", "素材地址不安全：仅允许 HTTPS", field=field)
        try:
            addresses = await self.resolver(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise AssetDownloadError("dns_failed", "素材域名解析失败", field=field) from exc
        if not addresses or any(_is_unsafe_address(item[-1][0]) for item in addresses):
            raise AssetDownloadError("url_unsafe", "素材地址不安全：禁止访问内部网络", field=field)

    async def _save_response(
        self,
        response: httpx.Response,
        original_url: str,
        directory: Path,
        stem: str,
        field: str,
        job_bytes: int,
    ) -> MaterializedAsset:
        declared = response.headers.get("content-type", "").split(";", 1)[0].lower()
        temporary = directory / f".{stem}.part"
        size = 0
        digest = hashlib.sha256()
        header = b""
        with temporary.open("wb") as output:
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_FILE_BYTES or job_bytes + size > MAX_JOB_BYTES:
                    raise AssetDownloadError("asset_too_large", "素材超过大小限制", field=field)
                header = (header + chunk)[:16]
                digest.update(chunk)
                output.write(chunk)
        mime_type, suffix = _detect_image(header)
        if mime_type is None or declared != mime_type:
            temporary.unlink(missing_ok=True)
            raise AssetDownloadError("asset_format_invalid", "素材响应 MIME 与真实文件格式不一致", field=field)
        destination = directory / f"{stem}{suffix}"
        temporary.replace(destination)
        return MaterializedAsset(original_url, destination, digest.hexdigest(), mime_type, size)


def _is_unsafe_address(raw: str) -> bool:
    try:
        address = ipaddress.ip_address(raw.split("%", 1)[0])
    except ValueError:
        return True
    return not address.is_global


def _detect_image(header: bytes) -> tuple[str | None, str]:
    for mime_type, suffix, magic in _MAGIC:
        if header.startswith(magic):
            if mime_type == "image/webp" and header[8:12] != b"WEBP":
                continue
            return mime_type, suffix
    return None, ""
