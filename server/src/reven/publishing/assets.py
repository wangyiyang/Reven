"""Secure, bounded materialization of remote publication images."""

import hashlib
import ipaddress
import logging
import os
import shutil
import socket
import ssl
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import urljoin, urlsplit
from uuid import UUID, uuid4

import httpcore
import httpx

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_JOB_BYTES = 50 * 1024 * 1024
MAX_REDIRECTS = 5
Resolver = Callable[..., Awaitable[list[tuple[Any, ...]]]]
logger = logging.getLogger(__name__)

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
    cover: MaterializedAsset | None
    staging_dir: Path | None = None
    final_dir: Path | None = None

    def final_view(self) -> "MaterializedAssets":
        if self.staging_dir is None or self.final_dir is None:
            return self
        final_dir = self.final_dir

        def project(asset: MaterializedAsset) -> MaterializedAsset:
            return MaterializedAsset(
                asset.original_url,
                final_dir / asset.path.name,
                asset.sha256,
                asset.mime_type,
                asset.size,
            )

        return MaterializedAssets(
            tuple(project(asset) for asset in self.images),
            project(self.cover) if self.cover else None,
            final_dir=self.final_dir,
        )


class PinnedRequester(Protocol):
    def stream(self, url: str, pinned_ip: str) -> Any: ...


async def default_resolver(host: str, port: int, *, type: int) -> list[tuple[Any, ...]]:
    loop = __import__("asyncio").get_running_loop()
    result = await loop.getaddrinfo(host, port, type=type)
    return cast(list[tuple[Any, ...]], result)


class PinnedNetworkBackend(httpcore.AsyncNetworkBackend):
    """Connect TCP to a validated IP while httpcore keeps origin Host and TLS SNI."""

    def __init__(
        self,
        pinned_ip: str,
        *,
        underlying: httpcore.AsyncNetworkBackend | None = None,
    ) -> None:
        self.pinned_ip = pinned_ip
        self.underlying = underlying or httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> httpcore.AsyncNetworkStream:
        del host
        return await self.underlying.connect_tcp(
            self.pinned_ip,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(
        self, path: str, timeout: float | None = None, socket_options: Any = None
    ) -> httpcore.AsyncNetworkStream:
        raise httpcore.ConnectError("Unix socket is disabled for remote assets")

    async def sleep(self, seconds: float) -> None:
        await self.underlying.sleep(seconds)


class _CoreResponseStream(httpx.AsyncByteStream):
    def __init__(self, stream: AsyncIterator[bytes]) -> None:
        self.stream = stream

    async def __aiter__(self) -> AsyncIterator[bytes]:
        async for chunk in self.stream:
            yield chunk

    async def aclose(self) -> None:
        close = getattr(self.stream, "aclose", None)
        if close is not None:
            await close()


class PinnedHttpTransport(httpx.AsyncBaseTransport):
    def __init__(
        self,
        pinned_ip: str,
        *,
        underlying: httpcore.AsyncNetworkBackend | None = None,
    ) -> None:
        self.pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl.create_default_context(),
            network_backend=PinnedNetworkBackend(pinned_ip, underlying=underlying),
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        core_request = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
        response = await self.pool.handle_async_request(core_request)
        return httpx.Response(
            response.status,
            headers=response.headers,
            stream=_CoreResponseStream(cast(AsyncIterator[bytes], response.stream)),
            extensions=response.extensions,
        )

    async def aclose(self) -> None:
        await self.pool.aclose()


class HttpcorePinnedRequester:
    @asynccontextmanager
    async def stream(self, url: str, pinned_ip: str) -> AsyncIterator[httpx.Response]:
        async with httpx.AsyncClient(
            transport=PinnedHttpTransport(pinned_ip),
            trust_env=False,
            timeout=httpx.Timeout(30),
        ) as client:
            async with client.stream("GET", url, follow_redirects=False) as response:
                yield response


class AssetMaterializer:
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

    async def materialize(self, job_id: UUID | str, image_urls: list[str], cover_url: str | None) -> MaterializedAssets:
        try:
            normalized_job_id = str(UUID(str(job_id)))
        except ValueError as exc:
            raise AssetDownloadError("filesystem_error", "发布任务标识无效", field="assets") from exc
        root = self._safe_root()
        job_root = root / "jobs" / normalized_job_id
        directory = job_root / "staging" / str(uuid4())
        final_dir = job_root / "snapshot"
        try:
            self._reject_symlink_components(directory, root)
            directory.mkdir(parents=True, exist_ok=False)
            result = await self._materialize(directory, image_urls, cover_url)
            return MaterializedAssets(result.images, result.cover, directory, final_dir)
        except AssetDownloadError:
            _discard_tree(directory)
            _remove_empty_parents(directory.parent, root / "jobs")
            raise
        except OSError as exc:
            _discard_tree(directory)
            _remove_empty_parents(directory.parent, root / "jobs")
            raise AssetDownloadError("filesystem_error", "素材文件写入失败，请检查存储空间", field="assets") from exc

    async def finalize(self, assets: MaterializedAssets) -> MaterializedAssets:
        if assets.staging_dir is None or assets.final_dir is None:
            return assets
        root = self._safe_root()
        self._reject_symlink_components(assets.staging_dir, root)
        self._reject_symlink_components(assets.final_dir, root)
        try:
            assets.staging_dir.replace(assets.final_dir)
            _remove_empty_parents(assets.staging_dir.parent, root / "jobs")
        except OSError as exc:
            raise AssetDownloadError("filesystem_error", "素材快照提交失败", field="assets") from exc
        return assets.final_view()

    async def discard(self, assets: MaterializedAssets) -> None:
        if assets.staging_dir is None:
            return
        _discard_tree(assets.staging_dir)
        _remove_empty_parents(assets.staging_dir.parent, self._safe_root() / "jobs")

    def _safe_root(self) -> Path:
        try:
            if self.data_root.is_symlink():
                raise AssetDownloadError("filesystem_error", "素材根目录不能是符号链接", field="assets")
            self.data_root.mkdir(parents=True, exist_ok=True)
            return self.data_root.resolve()
        except OSError as exc:
            raise AssetDownloadError("filesystem_error", "素材文件写入失败，请检查存储空间", field="assets") from exc

    @staticmethod
    def _reject_symlink_components(path: Path, root: Path) -> None:
        if not path.resolve(strict=False).is_relative_to(root):
            raise AssetDownloadError("filesystem_error", "素材路径越界", field="assets")
        current = root
        for part in path.relative_to(root).parts:
            current /= part
            if current.is_symlink():
                raise AssetDownloadError("filesystem_error", "素材路径不能包含符号链接", field="assets")

    async def _materialize(self, directory: Path, image_urls: list[str], cover_url: str | None) -> MaterializedAssets:
        total = 0
        images: list[MaterializedAsset] = []
        for ordinal, url in enumerate(image_urls, start=1):
            asset = await self._download(url, directory, f"image-{ordinal}", "images", total)
            total += asset.size
            images.append(asset)
        if cover_url is None:
            return MaterializedAssets(tuple(images), None)
        cover = await self._download(cover_url, directory, "cover", "cover", total)
        return MaterializedAssets(tuple(images), cover)

    async def _download(self, url: str, directory: Path, stem: str, field: str, job_bytes: int) -> MaterializedAsset:
        try:
            return await self._download_checked(url, directory, stem, field, job_bytes)
        except (httpx.HTTPError, httpcore.NetworkError, httpcore.ProtocolError, httpcore.TimeoutException) as exc:
            raise AssetDownloadError("download_failed", "素材网络请求失败，请稍后重试", field=field) from exc

    async def _download_checked(
        self, url: str, directory: Path, stem: str, field: str, job_bytes: int
    ) -> MaterializedAsset:
        current = url
        for redirect in range(MAX_REDIRECTS + 1):
            pinned_ip = await self._validated_ip(current, field)
            async with self.requester.stream(current, pinned_ip) as response:
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

    async def _validated_ip(self, url: str, field: str) -> str:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise AssetDownloadError("url_unsafe", "素材地址不安全：仅允许 HTTPS", field=field)
        try:
            addresses = await self.resolver(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
        except (OSError, ValueError) as exc:
            raise AssetDownloadError("dns_failed", "素材域名解析失败", field=field) from exc
        ips = [str(item[-1][0]) for item in addresses if item and isinstance(item[-1], tuple)]
        if not ips or any(_is_unsafe_address(ip) for ip in ips):
            raise AssetDownloadError("url_unsafe", "素材地址不安全：禁止访问内部网络", field=field)
        return ips[0]

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
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(temporary, flags, 0o600)
        with os.fdopen(descriptor, "wb") as output:
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


def _cleanup(directory: Path) -> bool:
    try:
        for path in directory.glob("*"):
            if path.is_file():
                path.unlink()
    except OSError:
        logger.warning("素材失败后的临时文件清理未完成")
        return False
    return True


def _discard_tree(directory: Path) -> None:
    try:
        if directory.exists() and not directory.is_symlink():
            shutil.rmtree(directory)
    except OSError:
        logger.warning("素材 staging 清理未完成")


def _remove_empty_parents(directory: Path, stop: Path) -> None:
    while directory != stop and directory.is_relative_to(stop):
        try:
            directory.rmdir()
        except OSError:
            return
        directory = directory.parent


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
