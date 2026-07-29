"""Notion 稿件库字段初始化：只增不删、幂等。

按 spec §6.3 补齐 ``封面`` / ``自动化状态`` / ``失败原因`` 字段，并为现有
``状态`` Status 字段追加 ``待发布`` / ``已交付`` 选项。绝不删除、重命名或
重新着色现有选项；已存在且类型不符的字段视为冲突，抛出带字段名的
``NotionSchemaError`` 交由人工处理。第二次执行时不发送任何 PATCH。
"""

from typing import Any

from reven.integrations.notion.client import NotionClient
from reven.integrations.notion.models import NotionSchemaError

COVER_PROPERTY = "封面"
AUTOMATION_STATUS_PROPERTY = "自动化状态"
FAILURE_REASON_PROPERTY = "失败原因"
STATUS_PROPERTY = "状态"

AUTOMATION_STATUS_OPTIONS: tuple[dict[str, str], ...] = (
    {"name": "未开始", "color": "gray"},
    {"name": "等待中", "color": "blue"},
    {"name": "处理中", "color": "yellow"},
    {"name": "阻塞", "color": "orange"},
    {"name": "失败", "color": "red"},
    {"name": "已完成", "color": "green"},
)

STATUS_OPTIONS_TO_APPEND = ("待发布", "已交付")


def compute_bootstrap_patch(properties: dict[str, Any]) -> dict[str, Any]:
    """计算最小 PATCH properties 负载；无需变更时返回空 dict。"""
    patch: dict[str, Any] = {}
    _ensure_typed_property(patch, properties, COVER_PROPERTY, "files")
    _ensure_typed_property(patch, properties, FAILURE_REASON_PROPERTY, "rich_text")
    _ensure_automation_status(patch, properties)
    _ensure_status_options(patch, properties)
    return patch


async def bootstrap_data_source_schema(client: NotionClient, data_source_id: str) -> dict[str, Any] | None:
    """读取当前数据源并只补齐缺失部分；无需变更时返回 None 且不发送 PATCH。"""
    data_source = await client.retrieve_data_source(data_source_id)
    properties = data_source.get("properties")
    if not isinstance(properties, dict):
        raise NotionSchemaError("数据源响应缺少 properties")
    patch = compute_bootstrap_patch(properties)
    if not patch:
        return None
    await client.update_data_source(data_source_id, properties=patch)
    return patch


def _ensure_typed_property(patch: dict[str, Any], properties: dict[str, Any], name: str, expected: str) -> None:
    prop = properties.get(name)
    if prop is None:
        patch[name] = {expected: {}}
        return
    _require_type(prop, name, expected)


def _ensure_automation_status(patch: dict[str, Any], properties: dict[str, Any]) -> None:
    prop = properties.get(AUTOMATION_STATUS_PROPERTY)
    if prop is None:
        options = [dict(option) for option in AUTOMATION_STATUS_OPTIONS]
        patch[AUTOMATION_STATUS_PROPERTY] = {"select": {"options": options}}
        return
    _require_type(prop, AUTOMATION_STATUS_PROPERTY, "select")
    existing = _option_names(prop, "select")
    missing = [dict(option) for option in AUTOMATION_STATUS_OPTIONS if option["name"] not in existing]
    if missing:
        options = _existing_options(prop, "select") + missing
        patch[AUTOMATION_STATUS_PROPERTY] = {"select": {"options": options}}


def _ensure_status_options(patch: dict[str, Any], properties: dict[str, Any]) -> None:
    prop = properties.get(STATUS_PROPERTY)
    if prop is None:
        raise NotionSchemaError(f"稿件库缺少必需的 {STATUS_PROPERTY} 字段，请先在 Notion 中创建 Status 字段")
    _require_type(prop, STATUS_PROPERTY, "status")
    existing = _option_names(prop, "status")
    missing = [{"name": name} for name in STATUS_OPTIONS_TO_APPEND if name not in existing]
    if missing:
        options = _existing_options(prop, "status") + missing
        patch[STATUS_PROPERTY] = {"status": {"options": options}}


def _require_type(prop: Any, name: str, expected: str) -> None:
    actual = prop.get("type") if isinstance(prop, dict) else None
    if actual != expected:
        raise NotionSchemaError(f"字段 {name} 类型应为 {expected}，实际为 {actual}，请手动调整后重试")


def _option_names(prop: dict[str, Any], config_key: str) -> set[str]:
    return {str(option.get("name")) for option in _existing_options(prop, config_key) if isinstance(option, dict)}


def _existing_options(prop: dict[str, Any], config_key: str) -> list[Any]:
    config = prop.get(config_key)
    if not isinstance(config, dict):
        return []
    options = config.get("options")
    return list(options) if isinstance(options, list) else []
