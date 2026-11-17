"""飞书多维表格（Bitable）领域能力：固定字段基准与资源绑定真实探针。

RSS 候选表的九个固定字段及类型基准为服务端常量；绑定测试按序执行
字段校验 → 只读查询 → 创建测试记录 → 删除测试记录，任一步失败即返回失败阶段
（外部同步表不支持删除时整体判失败）。所有错误沿用 FeishuBotApiError 脱敏纪律。
"""

import time
from collections.abc import Iterable
from dataclasses import dataclass
from uuid import uuid4

from reven.integrations.feishu_bot.client import (
    BitableField,
    BitableRecordWrite,
    FeishuBotApiClient,
    FeishuBotApiError,
)

# 官方字段类型数字编码
FIELD_TYPE_TEXT = 1  # 文本
FIELD_TYPE_SINGLE_SELECT = 3  # 单选
FIELD_TYPE_DATETIME = 5  # 日期
FIELD_TYPE_URL = 15  # 超链接

FIELD_TYPE_LABELS = {
    FIELD_TYPE_TEXT: "文本",
    FIELD_TYPE_SINGLE_SELECT: "单选",
    FIELD_TYPE_DATETIME: "日期",
    FIELD_TYPE_URL: "超链接",
}

# rss_candidates 用途的固定字段基准：字段名 → 期望类型
RSS_CANDIDATES_REQUIRED_FIELDS: tuple[tuple[str, int], ...] = (
    ("标题", FIELD_TYPE_TEXT),
    ("摘要", FIELD_TYPE_TEXT),
    ("来源", FIELD_TYPE_TEXT),
    ("发布时间", FIELD_TYPE_DATETIME),
    ("原文链接", FIELD_TYPE_URL),
    ("状态", FIELD_TYPE_SINGLE_SELECT),
    ("命中关键词", FIELD_TYPE_TEXT),
    ("入库日期", FIELD_TYPE_DATETIME),
    ("去重键", FIELD_TYPE_TEXT),
)

PROBE_STAGES = ("fields", "search", "create", "delete")


@dataclass(frozen=True)
class BitableProbeStage:
    """单个探针阶段结果：stage ∈ fields/search/create/delete。"""

    stage: str
    success: bool
    message: str | None = None


@dataclass(frozen=True)
class BitableProbeResult:
    """探针整体结果：stages 只含已执行阶段（失败即止步）。"""

    stages: tuple[BitableProbeStage, ...]

    @property
    def success(self) -> bool:
        return len(self.stages) == len(PROBE_STAGES) and all(stage.success for stage in self.stages)

    @property
    def failed_stage(self) -> str | None:
        for stage in self.stages:
            if not stage.success:
                return stage.stage
        return None


def validate_required_fields(
    fields: Iterable[BitableField],
    required: tuple[tuple[str, int], ...] = RSS_CANDIDATES_REQUIRED_FIELDS,
) -> str | None:
    """校验必需字段存在且类型匹配；失败返回固定格式的中文提示，通过返回 None。"""
    by_name = {field.name: field for field in fields}
    missing = [name for name, _ in required if name not in by_name]
    if missing:
        names = "、".join(f"「{name}」" for name in missing)
        return f"字段校验失败：缺少字段{names}"
    mismatched = [(name, expected) for name, expected in required if by_name[name].type != expected]
    if mismatched:
        details = "、".join(f"「{name}」应为{_type_label(expected)}" for name, expected in mismatched)
        return f"字段校验失败：字段类型不匹配（{details}）"
    return None


async def probe_rss_candidates_binding(api: FeishuBotApiClient, *, app_token: str, table_id: str) -> BitableProbeResult:
    """rss_candidates 绑定真实探针：字段校验 → 只读查询 → 创建 → 删除，失败即止步。"""
    stages: list[BitableProbeStage] = []

    try:
        fields = await api.list_fields(app_token, table_id)
    except FeishuBotApiError as exc:
        return _finish(stages, "fields", str(exc))
    if error := validate_required_fields(fields):
        return _finish(stages, "fields", error)
    stages.append(BitableProbeStage("fields", True))

    try:
        await api.search_records(app_token, table_id, page_size=1)
    except FeishuBotApiError as exc:
        return _finish(stages, "search", str(exc))
    stages.append(BitableProbeStage("search", True))

    try:
        created = await api.batch_create_records(app_token, table_id, [_probe_record()])
    except FeishuBotApiError as exc:
        return _finish(stages, "create", str(exc))
    stages.append(BitableProbeStage("create", True))

    try:
        await api.batch_delete_records(app_token, table_id, [record.record_id for record in created])
    except FeishuBotApiError as exc:
        return _finish(stages, "delete", f"{exc}（如为外部同步表，请在飞书侧解除同步后手动清理测试记录）")
    stages.append(BitableProbeStage("delete", True))
    return BitableProbeResult(tuple(stages))


def _finish(stages: list[BitableProbeStage], stage: str, message: str) -> BitableProbeResult:
    stages.append(BitableProbeStage(stage, False, message))
    return BitableProbeResult(tuple(stages))


def _type_label(field_type: int) -> str:
    return FIELD_TYPE_LABELS.get(field_type, f"类型编码 {field_type}")


def _probe_record() -> BitableRecordWrite:
    """绑定测试记录：不写入「状态」单选字段（选项可能未配置），字段校验阶段已覆盖其存在性。"""
    now_ms = int(time.time() * 1000)
    dedupe_key = f"reven-binding-test:{uuid4().hex}"
    return BitableRecordWrite(
        fields={
            "标题": "Reven 绑定测试记录",
            "摘要": "本记录由绑定测试探针创建，验证通过后会自动删除",
            "来源": "Reven",
            "发布时间": now_ms,
            "原文链接": {"link": "https://example.com/reven-binding-test", "text": "Reven 绑定测试"},
            "命中关键词": "绑定测试",
            "入库日期": now_ms,
            "去重键": dedupe_key,
        },
        client_token=dedupe_key,
    )
