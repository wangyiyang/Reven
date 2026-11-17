"""RSS 候选 Bitable 存储：Web 候选工作台与 Dashboard 统计的候选读写路径。

- 目标表由启用的 bitable/rss_candidates 资源绑定解析；未配置绑定、绑定配置非法、
  飞书凭证不可用、飞书 API 失败一律抛 503 领域错误（不静默降级为空列表）。
- 列表走 records/search（「状态」单选 filter + page_token 游标翻页，按发布时间/入库日期倒序）；
  计数优先用 search 返回的 total，缺失时翻页聚合兜底。
- 采纳/忽略先读后写：读到已是目标态 → 幂等返回原记录不重复写；读到其他非 candidate 状态
  （含飞书侧并发变更）→ 409 领域冲突，前端提示刷新。Bitable 无条件更新/事务，
  读与写之间的并发覆盖是设计容忍的固有限制。
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.integrations.bindings import (
    PURPOSE_RSS_CANDIDATES,
    RESOURCE_TYPE_BITABLE,
    FeishuResourceBindingService,
)
from reven.integrations.feishu_bot.bitable import bitable_text_value
from reven.integrations.feishu_bot.client import (
    BitableFilterCondition,
    BitableRecord,
    BitableRecordUpdate,
    BitableSortField,
    FeishuBotApiClient,
    FeishuBotApiError,
)
from reven.integrations.models import FeishuResourceBinding
from reven.provider_clients import ProviderClients
from reven.rss.bitable_writer import (
    ARCHIVED_AT_FIELD,
    DEDUPE_KEY_FIELD,
    KEYWORDS_FIELD,
    PUBLISHED_AT_FIELD,
    SOURCE_FIELD,
    STATUS_CANDIDATE,
    STATUS_FIELD,
    SUMMARY_FIELD,
    TITLE_FIELD,
    URL_FIELD,
)

CANDIDATE_STATUSES = ("candidate", "saved", "ignored")
CandidateTarget = Literal["saved", "ignored"]

# 计数查询的单页大小：只要 total，不需要记录内容
_COUNT_PAGE_SIZE = 1


class BitableCandidateStoreError(Exception):
    """候选存储领域错误：code + HTTP status_code 由路由原样映射；信息保持脱敏。"""

    def __init__(self, code: str, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class BitableCandidate:
    """Bitable 候选记录的领域映射（九个固定字段 + record_id）。"""

    record_id: str
    title: str
    summary: str
    source_name: str
    published_at: datetime | None
    url: str | None
    status: str
    matched_keywords: tuple[str, ...]
    archived_at: datetime | None
    dedupe_key: str


@dataclass(frozen=True)
class BitableCandidatePage:
    """候选列表单页：items + 匹配总数 + 下一页游标（无更多页为 None）。"""

    items: tuple[BitableCandidate, ...]
    total: int
    next_cursor: str | None


class BitableCandidateStore:
    """候选读写 seam：启用绑定解析 + ProviderClients 飞书客户端；无状态，可按请求构建。"""

    def __init__(self, factory: async_sessionmaker[AsyncSession], clients: ProviderClients | None) -> None:
        self._factory = factory
        self._clients = clients

    async def list_candidates(self, *, status: str, page_size: int, cursor: str | None) -> BitableCandidatePage:
        """按状态分页列出候选；cursor 为飞书 page_token 透传（None = 第一页）。"""
        api, app_token, table_id = await self._api_target()
        try:
            page = await api.search_records(
                app_token,
                table_id,
                filter_conditions=(BitableFilterCondition(STATUS_FIELD, "is", (status,)),),
                sort_fields=(
                    BitableSortField(PUBLISHED_AT_FIELD, desc=True),
                    BitableSortField(ARCHIVED_AT_FIELD, desc=True),
                ),
                page_size=page_size,
                page_token=cursor,
            )
        except FeishuBotApiError as exc:
            raise _unavailable(str(exc)) from exc
        return BitableCandidatePage(
            items=tuple(_to_candidate(record) for record in page.records),
            total=page.total if page.total is not None else len(page.records),
            next_cursor=page.page_token if page.has_more else None,
        )

    async def count_candidates(self, status: str) -> int:
        """按状态计数：优先 search 返回的 total；total 缺失时翻页聚合兜底。"""
        api, app_token, table_id = await self._api_target()
        try:
            first = await api.search_records(
                app_token,
                table_id,
                filter_conditions=(BitableFilterCondition(STATUS_FIELD, "is", (status,)),),
                page_size=_COUNT_PAGE_SIZE,
            )
            if first.total is not None:
                return first.total
            count = len(first.records)
            page_token = first.page_token
            has_more = first.has_more
            while has_more and page_token is not None:
                page = await api.search_records(
                    app_token,
                    table_id,
                    filter_conditions=(BitableFilterCondition(STATUS_FIELD, "is", (status,)),),
                    page_token=page_token,
                )
                count += len(page.records)
                has_more, page_token = page.has_more, page.page_token
            return count
        except FeishuBotApiError as exc:
            raise _unavailable(str(exc)) from exc

    async def set_status(self, record_id: str, target: CandidateTarget) -> BitableCandidate:
        """采纳/忽略：先读确认状态，仍是 candidate 才写目标态；已是目标态幂等返回。"""
        api, app_token, table_id = await self._api_target()
        record = await self._get_record(api, app_token, table_id, record_id)
        current = _to_candidate(record)
        if current.status == target:
            return current
        if current.status != STATUS_CANDIDATE:
            raise _status_conflict(target)
        try:
            updated = await api.batch_update_records(
                app_token,
                table_id,
                [BitableRecordUpdate(record_id=record_id, fields={STATUS_FIELD: target})],
            )
        except FeishuBotApiError as exc:
            raise _unavailable(str(exc)) from exc
        fresh = next((item for item in updated if item.record_id == record_id), None)
        if fresh is None:
            raise _unavailable("飞书多维表格记录更新响应缺少目标记录")
        return _to_candidate(fresh)

    async def _get_record(
        self, api: FeishuBotApiClient, app_token: str, table_id: str, record_id: str
    ) -> BitableRecord:
        try:
            record = await api.get_record(app_token, table_id, record_id)
        except FeishuBotApiError as exc:
            raise _unavailable(str(exc)) from exc
        if record is None:
            raise BitableCandidateStoreError("RSS_CANDIDATE_NOT_FOUND", "RSS 候选不存在或已被删除", status_code=404)
        return record

    async def _api_target(self) -> tuple[FeishuBotApiClient, str, str]:
        """解析启用绑定 + 飞书客户端；任一环缺失抛 503 领域错误。"""
        async with self._factory() as session:
            binding = await FeishuResourceBindingService(session).get_enabled_binding(PURPOSE_RSS_CANDIDATES)
        if binding is None:
            raise BitableCandidateStoreError(
                "RSS_CANDIDATES_BINDING_MISSING",
                "未配置启用的飞书多维表格绑定（bitable/rss_candidates）：请在飞书应用机器人集成中创建并启用候选表绑定",
                status_code=503,
            )
        app_token, table_id = _bitable_target(binding)
        if self._clients is None:
            raise _unavailable("飞书应用机器人未启用或凭证不可用")
        async with self._clients.feishu_bot() as bot:
            if bot is None:
                raise _unavailable("飞书应用机器人未启用或凭证不可用")
            return bot.api, app_token, table_id


def _bitable_target(binding: FeishuResourceBinding) -> tuple[str, str]:
    if binding.resource_type != RESOURCE_TYPE_BITABLE:
        raise _unavailable(f"绑定资源类型不支持：{binding.resource_type}")
    app_token = binding.config.get("app_token")
    table_id = binding.config.get("table_id")
    if not isinstance(app_token, str) or not app_token.strip():
        raise _unavailable("绑定配置数据无效（缺 app_token），请在飞书集成中更新或重新创建绑定")
    if not isinstance(table_id, str) or not table_id.strip():
        raise _unavailable("绑定配置数据无效（缺 table_id），请在飞书集成中更新或重新创建绑定")
    return app_token, table_id


def _unavailable(message: str) -> BitableCandidateStoreError:
    return BitableCandidateStoreError("RSS_CANDIDATES_UNAVAILABLE", message, status_code=503)


def _status_conflict(target: CandidateTarget) -> BitableCandidateStoreError:
    if target == "saved":
        return BitableCandidateStoreError(
            "RSS_CANDIDATE_NOT_SAVABLE",
            "RSS 候选状态已变更，当前状态不允许保存（请刷新列表）",
            status_code=409,
        )
    return BitableCandidateStoreError(
        "RSS_CANDIDATE_NOT_IGNORABLE",
        "RSS 候选状态已变更，当前状态不允许忽略（请刷新列表）",
        status_code=409,
    )


def _to_candidate(record: BitableRecord) -> BitableCandidate:
    fields = record.fields
    return BitableCandidate(
        record_id=record.record_id,
        title=bitable_text_value(fields.get(TITLE_FIELD)) or "",
        summary=bitable_text_value(fields.get(SUMMARY_FIELD)) or "",
        source_name=bitable_text_value(fields.get(SOURCE_FIELD)) or "",
        published_at=_datetime_field(fields.get(PUBLISHED_AT_FIELD)),
        url=_url_field(fields.get(URL_FIELD)),
        status=bitable_text_value(fields.get(STATUS_FIELD)) or "",
        matched_keywords=_keywords_value(fields.get(KEYWORDS_FIELD)),
        archived_at=_datetime_field(fields.get(ARCHIVED_AT_FIELD)),
        dedupe_key=bitable_text_value(fields.get(DEDUPE_KEY_FIELD)) or "",
    )


def _datetime_field(value: object) -> datetime | None:
    """Bitable 日期字段读路径为毫秒时间戳；非数字/缺省返回 None。"""
    if type(value) is int or type(value) is float:
        return datetime.fromtimestamp(value / 1000, tz=UTC)
    return None


def _url_field(value: object) -> str | None:
    """超链接字段读路径为 {link, text} 对象；兜底兼容纯文本形态。"""
    if isinstance(value, dict):
        link = value.get("link")
        return link if isinstance(link, str) and link else None
    if isinstance(value, str):
        return value or None
    return None


def _keywords_value(value: object) -> tuple[str, ...]:
    text = bitable_text_value(value)
    if not text:
        return ()
    return tuple(keyword for keyword in (part.strip() for part in text.split("、")) if keyword)
