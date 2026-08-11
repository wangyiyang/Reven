import socket
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
import pytest
from reven.rss.feed import FeedFetchError, SecureFeedReader
from reven.rss.models import RssSource

RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Example</title><item>
<guid>post-1</guid><link>https://example.com/posts/1</link>
<title>Agent &amp; systems</title><description><![CDATA[<p>Useful summary</p>]]></description>
<pubDate>Tue, 11 Aug 2026 01:00:00 GMT</pubDate>
</item></channel></rss>"""
ResponseFactory = Callable[[str], httpx.Response]


async def public_resolver(host: str, port: int, *, type: int) -> list[tuple[object, ...]]:
    del host, type
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]


class FakeRequester:
    def __init__(self, factory: ResponseFactory) -> None:
        self.factory = factory
        self.calls: list[tuple[str, str]] = []

    @asynccontextmanager
    async def stream(self, url: str, pinned_ip: str) -> AsyncIterator[httpx.Response]:
        self.calls.append((url, pinned_ip))
        response = self.factory(url)
        try:
            yield response
        finally:
            await response.aclose()


def source(url: str = "https://example.com/feed.xml") -> RssSource:
    return RssSource(id=uuid4(), name="Example", feed_url=url, enabled=True)


@pytest.mark.anyio
async def test_secure_feed_reader_parses_bounded_rss_through_pinned_ip() -> None:
    requester = FakeRequester(
        lambda url: httpx.Response(
            200,
            headers={"content-type": "application/rss+xml"},
            content=RSS,
            request=httpx.Request("GET", url),
        )
    )

    entries = await SecureFeedReader(requester=requester, resolver=public_resolver).fetch(source())

    assert requester.calls == [("https://example.com/feed.xml", "93.184.216.34")]
    assert len(entries) == 1
    assert entries[0].guid == "post-1"
    assert entries[0].title == "Agent & systems"
    assert entries[0].summary == "Useful summary"
    assert entries[0].published_at is not None


@pytest.mark.anyio
async def test_secure_feed_reader_rejects_private_dns_before_request() -> None:
    async def private_resolver(host: str, port: int, *, type: int) -> list[tuple[object, ...]]:
        del host, type
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]

    requester = FakeRequester(lambda url: httpx.Response(200, content=RSS, request=httpx.Request("GET", url)))

    with pytest.raises(FeedFetchError) as caught:
        await SecureFeedReader(requester=requester, resolver=private_resolver).fetch(source())

    assert caught.value.code == "RSS_URL_UNSAFE"
    assert requester.calls == []


@pytest.mark.anyio
async def test_secure_feed_reader_rejects_oversized_body(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("reven.rss.feed.MAX_FEED_BYTES", 10)
    requester = FakeRequester(lambda url: httpx.Response(200, content=RSS, request=httpx.Request("GET", url)))

    with pytest.raises(FeedFetchError) as caught:
        await SecureFeedReader(requester=requester, resolver=public_resolver).fetch(source())

    assert caught.value.code == "RSS_RESPONSE_TOO_LARGE"
