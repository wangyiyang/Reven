import hashlib
import socket
import ssl
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpcore
import httpx
import pytest
import reven.publishing.assets as assets_module
from reven.publishing.assets import (
    AssetDownloadError,
    AssetMaterializer,
    PinnedHttpTransport,
    PinnedNetworkBackend,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 20
ResponseFactory = Callable[[str, str], httpx.Response]


async def public_resolver(host: str, port: int, *, type: int) -> list[tuple[object, ...]]:
    del host, type
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]


class FakeRequester:
    def __init__(self, factory: ResponseFactory) -> None:
        self.factory = factory
        self.calls: list[tuple[str, str]] = []
        self.closed = 0

    @asynccontextmanager
    async def stream(self, url: str, pinned_ip: str) -> AsyncIterator[httpx.Response]:
        self.calls.append((url, pinned_ip))
        response = self.factory(url, pinned_ip)
        try:
            yield response
        finally:
            await response.aclose()
            self.closed += 1


def png_response(url: str, pinned_ip: str) -> httpx.Response:
    del pinned_ip
    return httpx.Response(200, headers={"content-type": "image/png"}, content=PNG, request=httpx.Request("GET", url))


@pytest.mark.anyio
async def test_materializer_uses_pinned_ip_sequential_names_and_hashes(tmp_path: Path) -> None:
    requester = FakeRequester(png_response)
    result = await AssetMaterializer(tmp_path, requester=requester, resolver=public_resolver).materialize(
        "job-1", ["https://example.com/image"], "https://example.com/cover"
    )

    assert requester.calls[0] == ("https://example.com/image", "93.184.216.34")
    assert result.images[0].path.name == "image-1.png"
    assert result.cover.path.name == "cover.png"
    assert result.images[0].sha256 == hashlib.sha256(PNG).hexdigest()


@pytest.mark.anyio
async def test_pinned_backend_connects_ip_but_preserves_tls_hostname() -> None:
    stream = FakeNetworkStream()
    underlying = FakeNetworkBackend(stream)
    backend = PinnedNetworkBackend("93.184.216.34", underlying=underlying)

    connected = await backend.connect_tcp("example.com", 443)
    await connected.start_tls(ssl.create_default_context(), server_hostname="example.com")

    assert underlying.hosts == ["93.184.216.34"]
    assert stream.server_hostnames == ["example.com"]


@pytest.mark.anyio
async def test_pinned_http_transport_preserves_host_header_and_sni() -> None:
    stream = FakeNetworkStream()
    underlying = FakeNetworkBackend(stream)
    async with httpx.AsyncClient(transport=PinnedHttpTransport("93.184.216.34", underlying=underlying)) as client:
        response = await client.get("https://example.com/image")

    assert response.status_code == 200
    assert underlying.hosts == ["93.184.216.34"]
    assert stream.server_hostnames == ["example.com"]
    assert b"Host: example.com\r\n" in b"".join(stream.writes)


@pytest.mark.anyio
async def test_materializer_rejects_rebinding_before_second_connection(tmp_path: Path) -> None:
    calls = 0

    async def resolver(host: str, port: int, *, type: int) -> list[tuple[object, ...]]:
        nonlocal calls
        del host, type
        calls += 1
        address = "93.184.216.34" if calls == 1 else "127.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

    requester = FakeRequester(
        lambda url, ip: httpx.Response(
            302,
            headers={"location": "https://example.com/next"},
            request=httpx.Request("GET", url),
        )
    )
    with pytest.raises(AssetDownloadError, match="内部网络"):
        await AssetMaterializer(tmp_path, requester=requester, resolver=resolver).materialize(
            "job-1", [], "https://example.com/cover"
        )

    assert requester.calls == [("https://example.com/cover", "93.184.216.34")]
    assert requester.closed == 1


@pytest.mark.anyio
async def test_materializer_rejects_private_dns_target(tmp_path: Path) -> None:
    async def resolver(host: str, port: int, *, type: int) -> list[tuple[object, ...]]:
        del host, type
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]

    with pytest.raises(AssetDownloadError, match="不安全"):
        await AssetMaterializer(tmp_path, requester=FakeRequester(png_response), resolver=resolver).materialize(
            "job-1", [], "https://localhost/cover"
        )


@pytest.mark.anyio
async def test_materializer_rejects_mime_magic_mismatch(tmp_path: Path) -> None:
    requester = FakeRequester(
        lambda url, ip: httpx.Response(
            200,
            headers={"content-type": "image/png"},
            content=b"not an image",
            request=httpx.Request("GET", url),
        )
    )
    with pytest.raises(AssetDownloadError, match="格式"):
        await AssetMaterializer(tmp_path, requester=requester, resolver=public_resolver).materialize(
            "job-1", [], "https://example.com/cover"
        )


@pytest.mark.anyio
async def test_redirect_hop_limit_closes_every_response(tmp_path: Path) -> None:
    requester = FakeRequester(
        lambda url, ip: httpx.Response(
            302, headers={"location": "https://example.com/next"}, request=httpx.Request("GET", url)
        )
    )
    with pytest.raises(AssetDownloadError) as caught:
        await AssetMaterializer(tmp_path, requester=requester, resolver=public_resolver).materialize(
            "job-1", [], "https://example.com/cover"
        )

    assert caught.value.code == "redirect_limit"
    assert len(requester.calls) == assets_module.MAX_REDIRECTS + 1
    assert requester.closed == len(requester.calls)


@pytest.mark.anyio
async def test_materializer_streaming_limit_removes_partial_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(assets_module, "MAX_FILE_BYTES", 10)
    with pytest.raises(AssetDownloadError, match="大小限制"):
        await AssetMaterializer(tmp_path, requester=FakeRequester(png_response), resolver=public_resolver).materialize(
            "job-1", [], "https://example.com/cover"
        )

    assert list((tmp_path / "jobs" / "job-1" / "snapshot").glob("*")) == []


@pytest.mark.anyio
async def test_materializer_classifies_network_failure(tmp_path: Path) -> None:
    class FailingRequester:
        @asynccontextmanager
        async def stream(self, url: str, pinned_ip: str) -> AsyncIterator[httpx.Response]:
            del url, pinned_ip
            raise httpx.ConnectError("signed-url-secret")
            yield

    with pytest.raises(AssetDownloadError) as caught:
        await AssetMaterializer(tmp_path, requester=FailingRequester(), resolver=public_resolver).materialize(
            "job-1", [], "https://example.com/cover?token=secret"
        )

    assert caught.value.code == "download_failed"
    assert "secret" not in str(caught.value)


@pytest.mark.anyio
async def test_materializer_enforces_cumulative_job_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(assets_module, "MAX_JOB_BYTES", len(PNG) + 5)
    with pytest.raises(AssetDownloadError, match="大小限制"):
        await AssetMaterializer(tmp_path, requester=FakeRequester(png_response), resolver=public_resolver).materialize(
            "job-1", ["https://example.com/image"], "https://example.com/cover"
        )

    assert list((tmp_path / "jobs" / "job-1" / "snapshot").glob("*")) == []


@pytest.mark.anyio
async def test_missing_cover_still_downloads_images_then_cleans_job_files(tmp_path: Path) -> None:
    requester = FakeRequester(png_response)

    result = await AssetMaterializer(tmp_path, requester=requester, resolver=public_resolver).materialize(
        "job-1", ["https://example.com/image"], None
    )

    assert len(result.images) == 1
    assert result.cover is None
    assert requester.calls == [("https://example.com/image", "93.184.216.34")]
    assert list((tmp_path / "jobs" / "job-1" / "snapshot").glob("*")) == []


@pytest.mark.anyio
async def test_resolver_and_filesystem_errors_are_structured_and_redacted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def bad_resolver(host: str, port: int, *, type: int) -> list[tuple[object, ...]]:
        del host, port, type
        raise RuntimeError("token=sensitive")

    with pytest.raises(AssetDownloadError) as dns_error:
        await AssetMaterializer(tmp_path, requester=FakeRequester(png_response), resolver=bad_resolver).materialize(
            "job-1", [], "https://example.com/cover?token=secret"
        )
    assert dns_error.value.code == "dns_failed"
    assert "sensitive" not in str(dns_error.value)

    monkeypatch.setattr(Path, "mkdir", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("private/path")))
    with pytest.raises(AssetDownloadError) as file_error:
        await AssetMaterializer(tmp_path, requester=FakeRequester(png_response), resolver=public_resolver).materialize(
            "job-1", [], "https://example.com/cover"
        )
    assert file_error.value.code == "filesystem_error"
    assert "private" not in str(file_error.value)


class FakeNetworkStream(httpcore.AsyncNetworkStream):
    def __init__(self) -> None:
        self.server_hostnames: list[str | None] = []
        self.writes: list[bytes] = []
        self.response = b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n"

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        del max_bytes, timeout
        response, self.response = self.response, b""
        return response

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:
        del timeout
        self.writes.append(buffer)

    async def aclose(self) -> None:
        return None

    async def start_tls(
        self,
        ssl_context: ssl.SSLContext,
        server_hostname: str | None = None,
        timeout: float | None = None,
    ) -> httpcore.AsyncNetworkStream:
        self.server_hostnames.append(server_hostname)
        return self


class FakeNetworkBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, stream: FakeNetworkStream) -> None:
        self.stream = stream
        self.hosts: list[str] = []

    async def connect_tcp(self, host: str, port: int, **kwargs: Any) -> httpcore.AsyncNetworkStream:
        del port, kwargs
        self.hosts.append(host)
        return self.stream

    async def connect_unix_socket(self, path: str, **kwargs: Any) -> httpcore.AsyncNetworkStream:
        raise AssertionError(path)

    async def sleep(self, seconds: float) -> None:
        return None
