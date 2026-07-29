"""Notion 页面 → ``MappedNotionPage`` 的字段映射。

按属性名读取、按属性 ``type`` 校验，不依赖属性顺序。缺少可选属性返回空值；
必需字段（标题/状态）缺失或任何字段类型不符时抛出带字段名的 ``NotionSchemaError``。
spec §6.2 中 ``系列 / 标签`` 与 ``摘要 / 核心观点`` 存在两种命名写法，映射时
按候选顺序取第一个存在的属性。
"""

from datetime import datetime
from typing import Any

from reven.integrations.notion.models import MappedNotionPage, NotionFile, NotionSchemaError

TITLE_PROPERTY = "标题"
STATUS_PROPERTY = "状态"
AUTOMATION_STATUS_PROPERTY = "自动化状态"
TARGET_CHANNELS_PROPERTY = "目标渠道"
PLANNED_PROPERTY = "计划发布日"
CATEGORY_PROPERTIES = ("系列", "标签")
SUMMARY_PROPERTIES = ("摘要", "核心观点")
COVER_PROPERTY = "封面"


def map_notion_page(page: dict[str, Any]) -> MappedNotionPage:
    properties = page.get("properties")
    if not isinstance(properties, dict):
        raise NotionSchemaError("Notion 页面缺少 properties")
    return MappedNotionPage(
        page_id=str(page.get("id", "")),
        url=str(page.get("url", "")),
        title=_read_title(properties),
        status=_read_status(properties),
        automation_status=_read_select(properties, AUTOMATION_STATUS_PROPERTY),
        target_channels=_read_multi_select(properties, TARGET_CHANNELS_PROPERTY),
        planned_raw=_read_date(properties, PLANNED_PROPERTY),
        categories=_read_first_multi_select(properties, CATEGORY_PROPERTIES),
        summary=_read_first_rich_text(properties, SUMMARY_PROPERTIES),
        cover=_read_cover(properties),
        last_edited_at=_parse_datetime(page.get("last_edited_time"), field="last_edited_time"),
    )


def _property(properties: dict[str, Any], name: str) -> dict[str, Any] | None:
    value = properties.get(name)
    return value if isinstance(value, dict) else None


def _require_type(prop: dict[str, Any], name: str, expected: str) -> None:
    actual = prop.get("type")
    if actual != expected:
        raise NotionSchemaError(f"字段 {name} 类型应为 {expected}，实际为 {actual}")


def _plain_text(items: Any) -> str:
    if not isinstance(items, list):
        return ""
    return "".join(str(item.get("plain_text", "")) for item in items if isinstance(item, dict))


def _read_title(properties: dict[str, Any]) -> str:
    prop = _property(properties, TITLE_PROPERTY)
    if prop is None:
        raise NotionSchemaError(f"稿件库缺少必需字段 {TITLE_PROPERTY}")
    _require_type(prop, TITLE_PROPERTY, "title")
    return _plain_text(prop.get("title"))


def _read_status(properties: dict[str, Any]) -> str:
    prop = _property(properties, STATUS_PROPERTY)
    if prop is None:
        raise NotionSchemaError(f"稿件库缺少必需字段 {STATUS_PROPERTY}")
    _require_type(prop, STATUS_PROPERTY, "status")
    return _option_name(prop.get("status"), STATUS_PROPERTY) or ""


def _read_select(properties: dict[str, Any], name: str) -> str | None:
    prop = _property(properties, name)
    if prop is None:
        return None
    _require_type(prop, name, "select")
    return _option_name(prop.get("select"), name)


def _option_name(value: Any, name: str) -> str | None:
    if value is None:
        return None
    option_name = value.get("name") if isinstance(value, dict) else None
    if not isinstance(option_name, str):
        raise NotionSchemaError(f"字段 {name} 的选项值格式异常")
    return option_name


def _read_multi_select(properties: dict[str, Any], name: str) -> list[str]:
    prop = _property(properties, name)
    if prop is None:
        return []
    _require_type(prop, name, "multi_select")
    options = prop.get("multi_select")
    if not isinstance(options, list):
        raise NotionSchemaError(f"字段 {name} 的 multi_select 值格式异常")
    return [str(option.get("name")) for option in options if isinstance(option, dict)]


def _read_rich_text(properties: dict[str, Any], name: str) -> str:
    prop = _property(properties, name)
    if prop is None:
        return ""
    _require_type(prop, name, "rich_text")
    return _plain_text(prop.get("rich_text"))


def _read_first_multi_select(properties: dict[str, Any], candidates: tuple[str, ...]) -> list[str]:
    for name in candidates:
        if _property(properties, name) is not None:
            return _read_multi_select(properties, name)
    return []


def _read_first_rich_text(properties: dict[str, Any], candidates: tuple[str, ...]) -> str:
    for name in candidates:
        if _property(properties, name) is not None:
            return _read_rich_text(properties, name)
    return ""


def _read_date(properties: dict[str, Any], name: str) -> str | None:
    prop = _property(properties, name)
    if prop is None:
        return None
    _require_type(prop, name, "date")
    value = prop.get("date")
    if value is None:
        return None
    if not isinstance(value, dict):
        raise NotionSchemaError(f"字段 {name} 的 date 值格式异常")
    start = value.get("start")
    return str(start) if start else None


def _read_cover(properties: dict[str, Any]) -> NotionFile | None:
    prop = _property(properties, COVER_PROPERTY)
    if prop is None:
        return None
    _require_type(prop, COVER_PROPERTY, "files")
    files = prop.get("files")
    if not isinstance(files, list):
        raise NotionSchemaError(f"字段 {COVER_PROPERTY} 的 files 值格式异常")
    if not files:
        return None
    first = files[0]
    if not isinstance(first, dict):
        raise NotionSchemaError(f"字段 {COVER_PROPERTY} 的文件项格式异常")
    file_type = first.get("type")
    if file_type == "file":
        inner = first.get("file")
        if not isinstance(inner, dict) or not isinstance(inner.get("url"), str):
            raise NotionSchemaError(f"字段 {COVER_PROPERTY} 的文件项缺少可下载地址")
        expiry_raw = inner.get("expiry_time")
        return NotionFile(
            name=str(first.get("name", "")),
            url=inner["url"],
            expiry_time=_parse_datetime(expiry_raw, field=COVER_PROPERTY) if expiry_raw else None,
        )
    if file_type == "external":
        inner = first.get("external")
        if not isinstance(inner, dict) or not isinstance(inner.get("url"), str):
            raise NotionSchemaError(f"字段 {COVER_PROPERTY} 的外链文件缺少地址")
        return NotionFile(name=str(first.get("name", "")), url=inner["url"])
    raise NotionSchemaError(f"字段 {COVER_PROPERTY} 包含不支持的文件类型 {file_type}")


def _parse_datetime(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise NotionSchemaError(f"字段 {field} 缺少 ISO 时间字符串")
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise NotionSchemaError(f"字段 {field} 的时间格式非法：{value}") from exc
