"""Pinned outbound HTTP transport preserving origin Host and TLS SNI."""

import ssl
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, Protocol, cast

import httpcore
import httpx

Resolver = Callable[..., Awaitable[list[tuple[Any, ...]]]]


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
        raise httpcore.ConnectError("Unix socket is disabled for outbound requests")

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
