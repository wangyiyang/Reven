"""RSS 候选 Bitable 写入器：候选唯一权威存储的写入路径（run 关键步骤）。

防重三层（Bitable 无数据库级唯一约束的固有限制下降低重复风险，不承诺绝对不重复）：
1. run 内 seen-set 兜底（discovery 收集时已按去重键去重）；
2. 写前按「去重键」字段分批 search 查重，已存在跳过（search 对新记录的可见时效无官方承诺）；
3. 稳定 client_token：同 run 同去重键 token 相同，重试时飞书侧幂等拒绝重复创建。
   注：飞书 client_token 有长度上限（64 字符），"{run_id}:{dedupe_key}" 原文约 105 字符超限，
   故取 "{run_id}:{sha256(dedupe_key)[:24]}"（61 字符），稳定性与唯一性语义不变。

同一绑定表的写入经 PG advisory lock 串行化（pg_advisory_xact_lock，key 含 binding id），
覆盖查重 → 创建窗口内的并发 writer。

「状态」单选字段：Bitable 对写入不存在的选项值没有可靠承诺（Commit 1 探针因此刻意不写状态），
故写前经 list_fields 预检「状态」字段必须已配置 candidate 选项；缺失时抛出带修复指引的领域
错误，由用户在飞书侧为「状态」添加 candidate / saved / ignored 选项后重跑（run 可重试）。
"""

import hashlib
from collections.abc import Iterator
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.integrations.bindings import (
    PURPOSE_RSS_CANDIDATES,
    RESOURCE_TYPE_BITABLE,
    FeishuResourceBindingService,
)
from reven.integrations.feishu_bot.bitable import bitable_text_value, validate_required_fields
from reven.integrations.feishu_bot.client import (
    BitableFilterCondition,
    BitableRecordWrite,
    FeishuBotApiClient,
    FeishuBotApiError,
)
from reven.integrations.models import FeishuResourceBinding
from reven.provider_clients import ProviderClients
from reven.rss.screening_service import ScreenedCandidate
from reven.scheduling import utc_now

# 固定字段名（与 bitable.RSS_CANDIDATES_REQUIRED_FIELDS 基准一致，测试断言对齐）
TITLE_FIELD = "标题"
SUMMARY_FIELD = "摘要"
SOURCE_FIELD = "来源"
PUBLISHED_AT_FIELD = "发布时间"
URL_FIELD = "原文链接"
STATUS_FIELD = "状态"
KEYWORDS_FIELD = "命中关键词"
ARCHIVED_AT_FIELD = "入库日期"
DEDUPE_KEY_FIELD = "去重键"

STATUS_CANDIDATE = "candidate"
# search 单条件 value 个数保守上限（官方未明确；值过多请求体过大），超出自动分批查询
_SEARCH_VALUES_PER_CONDITION = 100


class BitableCandidateWriteError(RuntimeError):
    """候选写入 Bitable 失败（run 级失败，触发整体重试）；信息保持脱敏（不含凭证/token/响应原文）。"""


def write_lock_key(binding_id: UUID) -> str:
    """同一绑定表的写入串行化锁 key（pg_advisory_xact_lock(hashtext(key))）。"""
    return f"reven:rss-candidates-bitable-write:{binding_id}"


class BitableCandidateWriter:
    """候选直写 Bitable：启用绑定解析 → advisory lock → 字段/选项预检 → 查重 → 批量创建。"""

    def __init__(self, factory: async_sessionmaker[AsyncSession], clients: ProviderClients) -> None:
        self._factory = factory
        self._clients = clients

    async def write_candidates(self, *, run_id: UUID, candidates: tuple[ScreenedCandidate, ...]) -> int:
        """把候选写入启用的 rss_candidates 绑定表，返回实际新创建的记录数。

        未配置启用绑定视为管线配置错误；飞书凭证不可用、字段/选项预检失败、API 失败
        均抛 BitableCandidateWriteError —— 写入失败 = run 失败（discovery 标记 failed，
        不推进 checkpoint、不发成功汇总，下轮重试由查重 + client_token 兜底幂等）。
        """
        binding = await self._enabled_binding()
        if binding is None:
            raise BitableCandidateWriteError(
                "未配置启用的飞书多维表格绑定（bitable/rss_candidates）：请在飞书应用机器人集成中创建并启用候选表绑定"
            )
        app_token, table_id = _bitable_target(binding)
        if not candidates:
            return 0
        async with self._clients.feishu_bot() as bot:
            if bot is None:
                raise BitableCandidateWriteError("飞书应用机器人未启用或凭证不可用，候选无法写入多维表格")
            api = bot.api
            async with self._factory.begin() as session:
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
                    {"lock_key": write_lock_key(binding.id)},
                )
                try:
                    await _preflight_fields(api, app_token, table_id)
                    fresh = await _dedupe_against_table(api, app_token, table_id, candidates)
                    if not fresh:
                        return 0
                    created = await api.batch_create_records(
                        app_token, table_id, [_record(run_id, candidate) for candidate in fresh]
                    )
                except FeishuBotApiError as exc:
                    raise BitableCandidateWriteError(str(exc)) from exc
        return len(created)

    async def _enabled_binding(self) -> FeishuResourceBinding | None:
        async with self._factory() as session:
            binding = await FeishuResourceBindingService(session).get_enabled_binding(PURPOSE_RSS_CANDIDATES)
        if binding is not None and binding.resource_type != RESOURCE_TYPE_BITABLE:
            raise BitableCandidateWriteError(f"绑定资源类型不支持：{binding.resource_type}")
        return binding


def _bitable_target(binding: FeishuResourceBinding) -> tuple[str, str]:
    config = binding.config
    app_token = config.get("app_token")
    table_id = config.get("table_id")
    if not isinstance(app_token, str) or not app_token.strip():
        raise BitableCandidateWriteError("绑定配置数据无效（缺 app_token），请在飞书集成中更新或重新创建绑定")
    if not isinstance(table_id, str) or not table_id.strip():
        raise BitableCandidateWriteError("绑定配置数据无效（缺 table_id），请在飞书集成中更新或重新创建绑定")
    return app_token, table_id


async def _preflight_fields(api: FeishuBotApiClient, app_token: str, table_id: str) -> None:
    """字段基准校验 + 「状态」单选选项预检（候选写入前失败，给出可执行修复指引）。"""
    fields = await api.list_fields(app_token, table_id)
    if error := validate_required_fields(fields):
        raise BitableCandidateWriteError(f"候选表字段基准不满足：{error}")
    status_options = next(field.options for field in fields if field.name == STATUS_FIELD)
    if STATUS_CANDIDATE not in status_options:
        raise BitableCandidateWriteError(
            f"候选表「{STATUS_FIELD}」字段缺少单选选项「{STATUS_CANDIDATE}」："
            f"请在飞书中为「{STATUS_FIELD}」字段添加 candidate / saved / ignored 选项后重试"
        )


async def _dedupe_against_table(
    api: FeishuBotApiClient,
    app_token: str,
    table_id: str,
    candidates: tuple[ScreenedCandidate, ...],
) -> tuple[ScreenedCandidate, ...]:
    """run 内 seen-set 兜底 + 按去重键分批 search 查重，返回表中尚不存在的候选。"""
    fresh: dict[str, ScreenedCandidate] = {}
    for candidate in candidates:
        fresh.setdefault(candidate.dedupe_key, candidate)
    existing = await _existing_dedupe_keys(api, app_token, table_id, tuple(fresh))
    return tuple(candidate for key, candidate in fresh.items() if key not in existing)


async def _existing_dedupe_keys(
    api: FeishuBotApiClient,
    app_token: str,
    table_id: str,
    keys: tuple[str, ...],
) -> set[str]:
    existing: set[str] = set()
    for chunk in _chunks(keys, _SEARCH_VALUES_PER_CONDITION):
        page_token: str | None = None
        while True:
            page = await api.search_records(
                app_token,
                table_id,
                filter_conditions=(BitableFilterCondition(DEDUPE_KEY_FIELD, "is", chunk),),
                page_token=page_token,
            )
            for record in page.records:
                if key := bitable_text_value(record.fields.get(DEDUPE_KEY_FIELD)):
                    existing.add(key)
            if page.has_more and page.page_token is not None:
                page_token = page.page_token
                continue
            break
    return existing


def _record(run_id: UUID, candidate: ScreenedCandidate) -> BitableRecordWrite:
    """九字段映射：标题/摘要用本地化中文文本（与候选工作台主展示口径一致）；无值字段整体省略。"""
    fields: dict[str, Any] = {
        TITLE_FIELD: candidate.title,
        SUMMARY_FIELD: candidate.summary,
        SOURCE_FIELD: candidate.source_name,
        STATUS_FIELD: STATUS_CANDIDATE,
        KEYWORDS_FIELD: "、".join(candidate.matched_keywords),
        ARCHIVED_AT_FIELD: _millis(utc_now()),
        DEDUPE_KEY_FIELD: candidate.dedupe_key,
    }
    if candidate.published_at is not None:
        fields[PUBLISHED_AT_FIELD] = _millis(candidate.published_at)
    if candidate.url:
        fields[URL_FIELD] = {"link": candidate.url, "text": candidate.title or candidate.url}
    return BitableRecordWrite(fields=fields, client_token=_client_token(run_id, candidate.dedupe_key))


def _client_token(run_id: UUID, dedupe_key: str) -> str:
    """稳定幂等 token：同 run 同去重键相同；对键取短哈希以满足飞书 client_token 长度上限。"""
    digest = hashlib.sha256(dedupe_key.encode()).hexdigest()[:24]
    return f"{run_id}:{digest}"


def _millis(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def _chunks(values: tuple[str, ...], size: int) -> Iterator[tuple[str, ...]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]
