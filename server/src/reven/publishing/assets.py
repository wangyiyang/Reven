"""Secure, bounded materialization of remote publication images."""

import hashlib
import ipaddress
import logging
import socket
import ssl
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import urljoin, urlsplit

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

    async def materialize(self, job_id: str, image_urls: list[str], cover_url: str | None) -> MaterializedAssets:
        directory = self.data_root / "jobs" / job_id / "snapshot"
        try:
            directory.mkdir(parents=True, exist_ok=True)
            return await self._materialize(directory, image_urls, cover_url)
        except AssetDownloadError:
            _cleanup(directory)
            raise
        except OSError as exc:
            _cleanup(directory)
            raise AssetDownloadError("filesystem_error", "素材文件写入失败，请检查存储空间", field="assets") from exc

    async def _materialize(self, directory: Path, image_urls: list[str], cover_url: str | None) -> MaterializedAssets:
        total = 0
        images: list[MaterializedAsset] = []
        for ordinal, url in enumerate(image_urls, start=1):
            asset = await self._download(url, directory, f"image-{ordinal}", "images", total)
            total += asset.size
            images.append(asset)
        if cover_url is None:
            if not _cleanup(directory):
                raise AssetDownloadError("filesystem_error", "素材临时文件清理失败", field="assets")
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


def _cleanup(directory: Path) -> bool:
    try:
        for path in directory.glob("*"):
            if path.is_file():
                path.unlink()
    except OSError:
        logger.warning("素材失败后的临时文件清理未完成")
        return False
    return True


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
