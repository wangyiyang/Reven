import ssl
from typing import Any

import httpcore
import httpx
import pytest
from reven.security.outbound import PinnedHttpTransport, PinnedNetworkBackend


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
