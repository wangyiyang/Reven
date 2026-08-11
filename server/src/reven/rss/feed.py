"""SSRF-safe and bounded RSS/Atom feed adapter."""

import ipaddress
import socket
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import NoReturn, cast
from urllib.parse import urljoin, urlsplit

import httpcore
import httpx
from bs4 import BeautifulSoup

from reven.publishing.assets import HttpcorePinnedRequester, PinnedRequester, Resolver, default_resolver
from reven.rss.discovery import FeedEntry
from reven.rss.models import RssSource

MAX_FEED_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 5


class FeedFetchError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class SecureFeedReader:
    def __init__(
        self,
        *,
        requester: PinnedRequester | None = None,
        resolver: Resolver = default_resolver,
    ) -> None:
        self._requester = requester or HttpcorePinnedRequester()
        self._resolver = resolver

    async def fetch(self, source: RssSource) -> tuple[FeedEntry, ...]:
        current = source.feed_url
        try:
            for redirect in range(MAX_REDIRECTS + 1):
                pinned_ip = await self._validated_ip(current)
                async with self._requester.stream(current, pinned_ip) as response:
                    if response.is_redirect:
                        current = _redirect_target(response, current, redirect)
                        continue
                    if not response.is_success:
                        _raise_for_status(response.status_code)
                    return _parse_feed(await _read_bounded(response))
        except FeedFetchError:
            raise
        except (httpx.HTTPError, httpcore.NetworkError, httpcore.ProtocolError, httpcore.TimeoutException) as exc:
            raise FeedFetchError("RSS_NETWORK_ERROR", "RSS 网络请求失败", retryable=True) from exc
        raise FeedFetchError("RSS_REDIRECT_LIMIT", "RSS 重定向次数过多")

    async def _validated_ip(self, url: str) -> str:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise FeedFetchError("RSS_URL_UNSAFE", "RSS 地址不安全：仅允许 HTTPS")
        try:
            addresses = await self._resolver(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
        except (OSError, ValueError) as exc:
            raise FeedFetchError("RSS_DNS_ERROR", "RSS 域名解析失败", retryable=True) from exc
        ips = [str(item[-1][0]) for item in addresses if item and isinstance(item[-1], tuple)]
        if not ips or any(_unsafe_ip(item) for item in ips):
            raise FeedFetchError("RSS_URL_UNSAFE", "RSS 地址不安全：禁止访问内部网络")
        return ips[0]


async def _read_bounded(response: httpx.Response) -> bytes:
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > MAX_FEED_BYTES:
            raise FeedFetchError("RSS_RESPONSE_TOO_LARGE", "RSS 响应超过大小限制")
        chunks.append(chunk)
    return b"".join(chunks)


def _parse_feed(payload: bytes) -> tuple[FeedEntry, ...]:
    lowered = payload[:4096].lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise FeedFetchError("RSS_XML_UNSAFE", "RSS XML 包含不安全声明")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise FeedFetchError("RSS_XML_INVALID", "RSS XML 格式无效") from exc
    if _local_name(root.tag) == "rss":
        return tuple(_rss_entry(item) for item in root.findall("./channel/item") if _text(item, "title"))
    if _local_name(root.tag) == "feed":
        return tuple(
            _atom_entry(item) for item in root if _local_name(item.tag) == "entry" and _child_text(item, "title")
        )
    raise FeedFetchError("RSS_FORMAT_UNSUPPORTED", "RSS 响应不是受支持的 RSS 或 Atom Feed")


def _rss_entry(item: ET.Element) -> FeedEntry:
    return FeedEntry(
        _text(item, "guid"),
        _text(item, "link"),
        _text(item, "title") or "",
        _plain_text(_text(item, "description") or _text(item, "summary") or ""),
        _parse_date(_text(item, "pubDate") or _text(item, "published")),
    )


def _atom_entry(item: ET.Element) -> FeedEntry:
    link = next(
        (
            child.attrib.get("href")
            for child in item
            if _local_name(child.tag) == "link" and child.attrib.get("rel", "alternate") == "alternate"
        ),
        None,
    )
    return FeedEntry(
        _child_text(item, "id"),
        link,
        _child_text(item, "title") or "",
        _plain_text(_child_text(item, "summary") or _child_text(item, "content") or ""),
        _parse_date(_child_text(item, "published") or _child_text(item, "updated")),
    )


def _text(item: ET.Element, name: str) -> str | None:
    child = item.find(name)
    return _element_text(child)


def _child_text(item: ET.Element, name: str) -> str | None:
    child = next((value for value in item if _local_name(value.tag) == name), None)
    return _element_text(child)


def _element_text(element: ET.Element | None) -> str | None:
    if element is None:
        return None
    value = "".join(element.itertext()).strip()
    return value or None


def _plain_text(value: str) -> str:
    return " ".join(BeautifulSoup(value, "html.parser").get_text(" ").split())


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _redirect_target(response: httpx.Response, current: str, redirect: int) -> str:
    if redirect == MAX_REDIRECTS:
        raise FeedFetchError("RSS_REDIRECT_LIMIT", "RSS 重定向次数过多")
    location = response.headers.get("location")
    if not location:
        raise FeedFetchError("RSS_REDIRECT_INVALID", "RSS 重定向地址无效")
    return cast(str, urljoin(current, location))


def _raise_for_status(status: int) -> NoReturn:
    retryable = status == 429 or status >= 500
    raise FeedFetchError("RSS_HTTP_ERROR", f"RSS 请求失败（HTTP {status}）", retryable=retryable)


def _unsafe_ip(raw: str) -> bool:
    try:
        address = ipaddress.ip_address(raw.split("%", 1)[0])
    except ValueError:
        return True
    return not address.is_global
