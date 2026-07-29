import copy

import pytest
from reven.integrations.notion.mapper import map_notion_page
from reven.integrations.notion.models import NotionSchemaError


def test_page_mapper_reads_editorial_fields(load_fixture) -> None:  # type: ignore[no-untyped-def]
    page = load_fixture("notion/page.json")
    mapped = map_notion_page(page)

    assert mapped.page_id == "11111111-1111-1111-1111-111111111111"
    assert mapped.title == "测试稿件"
    assert mapped.status == "待发布"
    assert mapped.target_channels == ["个人博客", "微信公众号"]
    assert mapped.planned_raw == "2026-08-01"
    assert mapped.cover is not None
    assert mapped.cover.url == "https://files.example.test/cover.png"


def test_page_mapper_reads_remaining_fields(load_fixture) -> None:  # type: ignore[no-untyped-def]
    mapped = map_notion_page(load_fixture("notion/page.json"))

    assert mapped.url == "https://www.notion.so/11111111111111111111111111111111"
    assert mapped.automation_status == "未开始"
    assert mapped.categories == ["工程实践"]
    assert mapped.summary == "这是一篇测试稿件的摘要。"
    assert mapped.cover is not None
    assert mapped.cover.name == "cover.png"
    assert mapped.cover.expiry_time is not None
    assert mapped.last_edited_at.isoformat() == "2026-07-28T12:30:00+00:00"


def _minimal_page() -> dict:
    return {
        "object": "page",
        "id": "11111111-1111-1111-1111-111111111111",
        "url": "https://www.notion.so/11111111111111111111111111111111",
        "last_edited_time": "2026-07-28T12:30:00.000Z",
        "properties": {
            "标题": {"id": "title", "type": "title", "title": [{"type": "text", "plain_text": "测试稿件"}]},
            "状态": {"id": "s", "type": "status", "status": {"id": "st4", "name": "待发布", "color": "blue"}},
        },
    }


def test_missing_optional_properties_map_to_empty_values() -> None:
    mapped = map_notion_page(_minimal_page())

    assert mapped.automation_status is None
    assert mapped.target_channels == []
    assert mapped.planned_raw is None
    assert mapped.categories == []
    assert mapped.summary == ""
    assert mapped.cover is None


def test_missing_required_status_property_raises_schema_error() -> None:
    page = _minimal_page()
    del page["properties"]["状态"]

    with pytest.raises(NotionSchemaError, match="状态"):
        map_notion_page(page)


def test_wrongly_typed_title_raises_schema_error_naming_field() -> None:
    page = _minimal_page()
    page["properties"]["标题"] = {"id": "title", "type": "rich_text", "rich_text": []}

    with pytest.raises(NotionSchemaError, match="标题"):
        map_notion_page(page)


def test_null_status_value_maps_to_empty_string() -> None:
    page = _minimal_page()
    page["properties"]["状态"]["status"] = None

    assert map_notion_page(page).status == ""


def test_summary_falls_back_to_core_viewpoint_property() -> None:
    page = _minimal_page()
    page["properties"]["核心观点"] = {
        "id": "sum",
        "type": "rich_text",
        "rich_text": [{"type": "text", "plain_text": "核心观点摘要"}],
    }

    assert map_notion_page(page).summary == "核心观点摘要"


def test_categories_fall_back_to_tag_property() -> None:
    page = _minimal_page()
    page["properties"]["标签"] = {
        "id": "tag",
        "type": "multi_select",
        "multi_select": [{"id": "t1", "name": "AI", "color": "red"}],
    }

    assert map_notion_page(page).categories == ["AI"]


def test_planned_datetime_keeps_raw_string() -> None:
    page = _minimal_page()
    page["properties"]["计划发布日"] = {
        "id": "plan",
        "type": "date",
        "date": {"start": "2026-08-01T09:30:00.000+08:00", "end": None, "time_zone": None},
    }

    assert map_notion_page(page).planned_raw == "2026-08-01T09:30:00.000+08:00"


def test_external_cover_file_is_supported_without_expiry() -> None:
    page = _minimal_page()
    page["properties"]["封面"] = {
        "id": "cov",
        "type": "files",
        "files": [
            {
                "name": "cover.png",
                "type": "external",
                "external": {"url": "https://static.example.test/cover.png"},
            }
        ],
    }

    cover = map_notion_page(page).cover
    assert cover is not None
    assert cover.url == "https://static.example.test/cover.png"
    assert cover.expiry_time is None


def test_cover_reads_first_file_only(load_fixture) -> None:  # type: ignore[no-untyped-def]
    page = copy.deepcopy(load_fixture("notion/page.json"))
    page["properties"]["封面"]["files"].append(
        {
            "name": "second.png",
            "type": "external",
            "external": {"url": "https://static.example.test/second.png"},
        }
    )

    cover = map_notion_page(page).cover
    assert cover is not None
    assert cover.url == "https://files.example.test/cover.png"


def test_wrongly_typed_optional_property_raises_schema_error() -> None:
    page = _minimal_page()
    page["properties"]["目标渠道"] = {"id": "chan", "type": "select", "select": None}

    with pytest.raises(NotionSchemaError, match="目标渠道"):
        map_notion_page(page)
