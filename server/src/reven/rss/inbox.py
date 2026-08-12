"""Idempotently push a human-confirmed RSS candidate into Notion Inbox."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.rss.models import RssItem
from reven.scheduling import utc_now

PUSH_LEASE = timedelta(minutes=5)


class NotionInboxClient(Protocol):
    async def retrieve_data_source(self, data_source_id: str) -> dict[str, object]: ...

    async def query_data_source(
        self,
        data_source_id: str,
        *,
        filter: dict[str, object],
    ) -> dict[str, object]: ...

    async def create_page(self, data_source_id: str, *, properties: dict[str, object]) -> dict[str, object]: ...


class InboxPushError(Exception):
    def __init__(self, code: str, message: str, *, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class InboxPushResult:
    item_id: UUID
    notion_page_id: UUID
    notion_url: str


@dataclass(frozen=True)
class _MaterialSnapshot:
    id: UUID
    token: UUID
    title: str
    summary: str
    source_name: str
    url: str | None
    published_at: datetime | None


class RssInboxService:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        notion: NotionInboxClient,
        inbox_data_source_id: str,
    ) -> None:
        self._factory = factory
        self._notion = notion
        self._inbox_data_source_id = inbox_data_source_id

    async def push(self, item_id: UUID) -> InboxPushResult:
        claimed = await self._claim(item_id)
        if isinstance(claimed, InboxPushResult):
            return claimed
        try:
            page = await self._find_existing(claimed.id)
            if page is None:
                source_type = await self._source_property_type()
                page = await self._notion.create_page(
                    self._inbox_data_source_id,
                    properties=_notion_properties(claimed, source_type=source_type),
                )
            page_id, notion_url = _page_identity(page)
            return await self._complete(claimed, page_id, notion_url)
        except Exception as exc:
            await self._fail(claimed, type(exc).__name__)
            raise

    async def _claim(self, item_id: UUID) -> _MaterialSnapshot | InboxPushResult:
        async with self._factory.begin() as session:
            item = await session.get(RssItem, item_id, with_for_update=True)
            if item is None:
                raise InboxPushError("RSS_CANDIDATE_NOT_FOUND", "RSS 候选不存在", status_code=404)
            if item.status == "pushed":
                if item.notion_page_id is None or item.notion_url is None:
                    raise InboxPushError("RSS_PUSH_STATE_INVALID", "RSS 候选推送状态不完整", status_code=500)
                return InboxPushResult(item.id, item.notion_page_id, item.notion_url)
            now = utc_now()
            active_lease = (
                item.status == "pushing"
                and item.push_token is not None
                and item.push_started_at is not None
                and item.push_started_at >= now - PUSH_LEASE
            )
            if active_lease:
                raise InboxPushError("RSS_CANDIDATE_PUSH_IN_PROGRESS", "RSS 候选正在推送，请稍后重试")
            if item.status not in {"candidate", "pushing"}:
                raise InboxPushError("RSS_CANDIDATE_NOT_PUSHABLE", "RSS 候选当前状态不允许推送")
            token = uuid4()
            item.status = "pushing"
            item.push_token = token
            item.push_started_at = now
            item.push_error = None
            return _MaterialSnapshot(
                item.id,
                token,
                item.title_zh,
                item.summary_zh,
                item.source_name,
                item.url,
                item.published_at,
            )

    async def _find_existing(self, item_id: UUID) -> dict[str, object] | None:
        result = await self._notion.query_data_source(
            self._inbox_data_source_id,
            filter={"property": "Reven ID", "rich_text": {"equals": str(item_id)}},
        )
        pages = result.get("results")
        if not isinstance(pages, list):
            raise InboxPushError("NOTION_INBOX_RESPONSE_INVALID", "Notion Inbox 查询响应无效", status_code=502)
        if len(pages) > 1:
            raise InboxPushError("NOTION_INBOX_DUPLICATE", "Notion Inbox 存在重复 Reven ID")
        page = pages[0] if pages else None
        if page is not None and not isinstance(page, dict):
            raise InboxPushError("NOTION_INBOX_RESPONSE_INVALID", "Notion Inbox 页面响应无效", status_code=502)
        return page

    async def _source_property_type(self) -> str:
        data_source = await self._notion.retrieve_data_source(self._inbox_data_source_id)
        properties = data_source.get("properties")
        source = properties.get("来源") if isinstance(properties, dict) else None
        source_type = source.get("type") if isinstance(source, dict) else None
        if not isinstance(source_type, str) or source_type not in {"rich_text", "select"}:
            raise InboxPushError("NOTION_INBOX_SCHEMA_INVALID", "Notion Inbox 来源字段类型无效")
        return source_type

    async def _complete(self, snapshot: _MaterialSnapshot, page_id: UUID, notion_url: str) -> InboxPushResult:
        async with self._factory.begin() as session:
            item = await session.get(RssItem, snapshot.id, with_for_update=True)
            if item is None or item.status != "pushing" or item.push_token != snapshot.token:
                raise InboxPushError("RSS_PUSH_LEASE_LOST", "RSS 候选推送租约已失效")
            item.status = "pushed"
            item.notion_page_id = page_id
            item.notion_url = notion_url
            item.push_token = None
            item.push_started_at = None
            item.push_error = None
            item.pushed_at = utc_now()
        return InboxPushResult(snapshot.id, page_id, notion_url)

    async def _fail(self, snapshot: _MaterialSnapshot, error_type: str) -> None:
        async with self._factory.begin() as session:
            item = await session.get(RssItem, snapshot.id, with_for_update=True)
            if item is None or item.push_token != snapshot.token:
                return
            item.status = "candidate"
            item.push_token = None
            item.push_started_at = None
            item.push_error = error_type[:120]


def _notion_properties(item: _MaterialSnapshot, *, source_type: str) -> dict[str, object]:
    source: dict[str, object]
    if source_type == "select":
        source = {"select": {"name": item.source_name[:100]}}
    else:
        source = {"rich_text": [_rich_text(item.source_name)]}
    return {
        "名称": {"title": [_rich_text(item.title)]},
        "Reven ID": {"rich_text": [_rich_text(str(item.id))]},
        "来源": source,
        "原文链接": {"url": item.url[:2000] if item.url else None},
        "发布时间": {"date": {"start": item.published_at.isoformat()} if item.published_at else None},
        "摘要": {"rich_text": [_rich_text(item.summary)] if item.summary else []},
    }


def _rich_text(value: str) -> dict[str, object]:
    return {"type": "text", "text": {"content": value[:2000]}}


def _page_identity(page: dict[str, object]) -> tuple[UUID, str]:
    raw_id = page.get("id")
    raw_url = page.get("url")
    try:
        page_id = UUID(str(raw_id))
    except ValueError as exc:
        raise InboxPushError("NOTION_INBOX_RESPONSE_INVALID", "Notion Inbox 页面 ID 无效", status_code=502) from exc
    if not isinstance(raw_url, str):
        raise InboxPushError("NOTION_INBOX_RESPONSE_INVALID", "Notion Inbox 页面 URL 无效", status_code=502)
    parsed = urlsplit(raw_url)
    if parsed.scheme != "https" or parsed.hostname not in {"notion.so", "www.notion.so", "app.notion.com"}:
        raise InboxPushError("NOTION_INBOX_RESPONSE_INVALID", "Notion Inbox 页面 URL 无效", status_code=502)
    return page_id, raw_url
