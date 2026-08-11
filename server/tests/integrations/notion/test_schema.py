import copy
from typing import Any

import httpx
import pytest
import respx
from reven.integrations.notion.client import NotionClient
from reven.integrations.notion.models import NotionSchemaError
from reven.integrations.notion.schema import (
    bootstrap_data_source_schema,
    compute_bootstrap_patch,
    compute_inbox_patch,
)

BASE_URL = "https://api.notion.com"
TOKEN = "ntn_test_token_0000"
DATA_SOURCE_ID = "33333333-3333-3333-3333-333333333333"
INBOX_DATA_SOURCE_ID = "44444444-4444-4444-4444-444444444444"

EXPECTED_AUTOMATION_OPTIONS = ["未开始", "等待中", "处理中", "阻塞", "失败", "已完成"]


def _merge_properties(properties: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """模拟 Notion 服务端合并语义：select/status 的 options 以提交数组整体替换。"""
    merged = copy.deepcopy(properties)
    for name, config in patch.items():
        prop_type = next(iter(config))
        prop = merged.get(name, {"id": name, "name": name})
        prop["type"] = prop_type
        prop[prop_type] = config[prop_type]
        merged[name] = prop
    return merged


def test_compute_patch_adds_missing_properties_and_status_options(load_fixture) -> None:  # type: ignore[no-untyped-def]
    data_source = load_fixture("notion/data_source.json")

    patch = compute_bootstrap_patch(data_source["properties"])

    assert set(patch) == {"封面", "自动化状态", "失败原因", "状态"}
    assert patch["封面"] == {"files": {}}
    assert patch["失败原因"] == {"rich_text": {}}
    automation_options = patch["自动化状态"]["select"]["options"]
    assert [option["name"] for option in automation_options] == EXPECTED_AUTOMATION_OPTIONS

    status_options = patch["状态"]["status"]["options"]
    # 现有选项原样保留（不重命名、不删除、不重新着色），仅在末尾追加缺失项
    assert status_options[:3] == [
        {"id": "st1", "name": "选题池", "color": "gray"},
        {"id": "st2", "name": "撰写中", "color": "blue"},
        {"id": "st3", "name": "已发布", "color": "green"},
    ]
    assert status_options[3:] == [{"name": "待发布"}, {"name": "已交付"}]


def test_compute_patch_is_idempotent_after_merge(load_fixture) -> None:  # type: ignore[no-untyped-def]
    data_source = load_fixture("notion/data_source.json")
    first_patch = compute_bootstrap_patch(data_source["properties"])
    assert first_patch

    merged = _merge_properties(data_source["properties"], first_patch)
    assert compute_bootstrap_patch(merged) == {}


def test_compute_patch_appends_only_missing_select_options(load_fixture) -> None:  # type: ignore[no-untyped-def]
    data_source = load_fixture("notion/data_source.json")
    data_source["properties"]["自动化状态"] = {
        "id": "auto",
        "name": "自动化状态",
        "type": "select",
        "select": {"options": [{"id": "as1", "name": "未开始", "color": "gray"}]},
    }

    patch = compute_bootstrap_patch(data_source["properties"])

    options = patch["自动化状态"]["select"]["options"]
    assert options[0] == {"id": "as1", "name": "未开始", "color": "gray"}
    assert [option["name"] for option in options] == EXPECTED_AUTOMATION_OPTIONS
    assert "封面" in patch  # 其余缺失字段仍然补齐


def test_compute_patch_does_not_duplicate_existing_status_options(load_fixture) -> None:  # type: ignore[no-untyped-def]
    data_source = load_fixture("notion/data_source.json")
    data_source["properties"]["状态"]["status"]["options"].append({"id": "st4", "name": "待发布", "color": "purple"})

    patch = compute_bootstrap_patch(data_source["properties"])

    status_options = patch["状态"]["status"]["options"]
    assert [option["name"] for option in status_options].count("待发布") == 1
    assert status_options[-1] == {"name": "已交付"}


def test_conflicting_property_type_raises_schema_error(load_fixture) -> None:  # type: ignore[no-untyped-def]
    data_source = load_fixture("notion/data_source.json")
    data_source["properties"]["封面"] = {"id": "cov", "name": "封面", "type": "rich_text", "rich_text": {}}

    with pytest.raises(NotionSchemaError, match="封面"):
        compute_bootstrap_patch(data_source["properties"])


def test_select_property_without_config_key_is_treated_as_empty_options(load_fixture) -> None:  # type: ignore[no-untyped-def]
    data_source = load_fixture("notion/data_source.json")
    data_source["properties"]["自动化状态"] = {"id": "auto", "name": "自动化状态", "type": "select"}

    patch = compute_bootstrap_patch(data_source["properties"])

    options = patch["自动化状态"]["select"]["options"]
    assert [option["name"] for option in options] == EXPECTED_AUTOMATION_OPTIONS


def test_missing_status_property_raises_schema_error() -> None:
    with pytest.raises(NotionSchemaError, match="状态"):
        compute_bootstrap_patch({"标题": {"id": "title", "type": "title", "title": {}}})


def test_inbox_patch_adds_material_fields_and_bidirectional_article_relation() -> None:
    properties = {"名称": {"id": "title", "name": "名称", "type": "title", "title": {}}}

    patch = compute_inbox_patch(properties, DATA_SOURCE_ID)

    assert patch == {
        "Reven ID": {"rich_text": {}},
        "来源": {"rich_text": {}},
        "原文链接": {"url": {}},
        "发布时间": {"date": {}},
        "摘要": {"rich_text": {}},
        "关联稿件": {
            "relation": {
                "data_source_id": DATA_SOURCE_ID,
                "dual_property": {"synced_property_name": "关联素材"},
            }
        },
    }


def test_inbox_patch_is_idempotent_for_existing_bidirectional_relation() -> None:
    properties = {
        "名称": {"id": "title", "name": "名称", "type": "title", "title": {}},
        "Reven ID": {"id": "rid", "name": "Reven ID", "type": "rich_text", "rich_text": {}},
        "来源": {"id": "src", "name": "来源", "type": "rich_text", "rich_text": {}},
        "原文链接": {"id": "url", "name": "原文链接", "type": "url", "url": {}},
        "发布时间": {"id": "date", "name": "发布时间", "type": "date", "date": {}},
        "摘要": {"id": "sum", "name": "摘要", "type": "rich_text", "rich_text": {}},
        "关联稿件": {
            "id": "rel",
            "name": "关联稿件",
            "type": "relation",
            "relation": {
                "data_source_id": DATA_SOURCE_ID,
                "dual_property": {"synced_property_id": "back", "synced_property_name": "关联素材"},
            },
        },
    }

    assert compute_inbox_patch(properties, DATA_SOURCE_ID) == {}


def test_inbox_relation_to_wrong_data_source_is_rejected() -> None:
    properties = {
        "名称": {"id": "title", "name": "名称", "type": "title", "title": {}},
        "关联稿件": {
            "id": "rel",
            "name": "关联稿件",
            "type": "relation",
            "relation": {"data_source_id": INBOX_DATA_SOURCE_ID, "dual_property": {}},
        },
    }

    with pytest.raises(NotionSchemaError, match="关联稿件"):
        compute_inbox_patch(properties, DATA_SOURCE_ID)


@pytest.mark.anyio
async def test_bootstrap_gets_then_patches_minimal_payload(load_fixture) -> None:  # type: ignore[no-untyped-def]
    data_source = load_fixture("notion/data_source.json")
    with respx.mock(base_url=BASE_URL) as router:
        router.get(f"/v1/data_sources/{DATA_SOURCE_ID}").mock(return_value=httpx.Response(200, json=data_source))
        patch_route = router.patch(f"/v1/data_sources/{DATA_SOURCE_ID}").mock(
            return_value=httpx.Response(200, json={"object": "data_source", "id": DATA_SOURCE_ID})
        )
        async with httpx.AsyncClient(base_url=BASE_URL) as http:
            patch = await bootstrap_data_source_schema(NotionClient(token=TOKEN, http=http), DATA_SOURCE_ID)

    assert patch is not None
    import json

    payload = json.loads(patch_route.calls[0].request.content)
    assert payload == {"properties": patch}
    assert set(payload["properties"]) == {"封面", "自动化状态", "失败原因", "状态"}


@pytest.mark.anyio
async def test_bootstrap_second_run_sends_no_patch(load_fixture) -> None:  # type: ignore[no-untyped-def]
    data_source = load_fixture("notion/data_source.json")
    merged = copy.deepcopy(data_source)
    merged["properties"] = _merge_properties(
        data_source["properties"], compute_bootstrap_patch(data_source["properties"])
    )
    with respx.mock(base_url=BASE_URL, assert_all_called=False) as router:
        router.get(f"/v1/data_sources/{DATA_SOURCE_ID}").mock(return_value=httpx.Response(200, json=merged))
        patch_route = router.patch(f"/v1/data_sources/{DATA_SOURCE_ID}").mock(
            return_value=httpx.Response(200, json={"object": "data_source", "id": DATA_SOURCE_ID})
        )
        async with httpx.AsyncClient(base_url=BASE_URL) as http:
            patch = await bootstrap_data_source_schema(NotionClient(token=TOKEN, http=http), DATA_SOURCE_ID)

    assert patch is None
    assert not patch_route.called
