"""Notion 连接测试适配器与 bootstrap-schema 端点的 API 级测试（respx 拦截 Notion 流量）。"""

import copy
import json
from typing import Any

import httpx
import respx
from fastapi.testclient import TestClient

NOTION_BASE = "https://api.notion.com"
DATA_SOURCE_ID = "33333333-3333-3333-3333-333333333333"
DATABASE_ID = "22222222-2222-2222-2222-222222222222"
TOKEN = "ntn_0000cccc"


def _put_notion(client: TestClient, *, with_secret: bool = True) -> None:
    payload: dict[str, Any] = {"public_config": {"data_source_id": DATA_SOURCE_ID, "database_id": DATABASE_ID}}
    if with_secret:
        payload["secret"] = {"token": TOKEN}
    response = client.put("/api/integrations/notion", json=payload)
    assert response.status_code == 200


def _merge_properties(data_source: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(data_source)
    for name, config in patch.items():
        prop_type = next(iter(config))
        prop = merged["properties"].get(name, {"id": name, "name": name})
        prop["type"] = prop_type
        prop[prop_type] = config[prop_type]
        merged["properties"][name] = prop
    return merged


def test_notion_connection_test_success(client: TestClient, load_fixture) -> None:  # type: ignore[no-untyped-def]
    _put_notion(client)
    with respx.mock(base_url=NOTION_BASE) as router:
        router.get(f"/v1/data_sources/{DATA_SOURCE_ID}").mock(
            return_value=httpx.Response(200, json=load_fixture("notion/data_source.json"))
        )
        response = client.post("/api/integrations/notion/test")

    assert response.status_code == 200
    body = response.json()
    assert body["connection_status"] == "连接正常"
    assert body["last_error"] is None
    assert body["last_tested_at"] is not None


def test_notion_connection_test_config_error_is_redacted(client: TestClient) -> None:
    _put_notion(client)
    with respx.mock(base_url=NOTION_BASE) as router:
        router.get(f"/v1/data_sources/{DATA_SOURCE_ID}").mock(
            return_value=httpx.Response(401, json={"message": f"API token {TOKEN} is invalid"})
        )
        response = client.post("/api/integrations/notion/test")

    assert response.status_code == 200
    body = response.json()
    assert body["connection_status"] == "连接失败"
    assert body["last_error"] is not None
    assert TOKEN not in body["last_error"]
    assert TOKEN not in response.text


def test_notion_connection_test_never_calls_bootstrap(client: TestClient, load_fixture) -> None:  # type: ignore[no-untyped-def]
    _put_notion(client)
    with respx.mock(base_url=NOTION_BASE, assert_all_called=False) as router:
        router.get(f"/v1/data_sources/{DATA_SOURCE_ID}").mock(
            return_value=httpx.Response(200, json=load_fixture("notion/data_source.json"))
        )
        patch_route = router.patch(f"/v1/data_sources/{DATA_SOURCE_ID}").mock(
            return_value=httpx.Response(200, json={"object": "data_source"})
        )
        response = client.post("/api/integrations/notion/test")

    assert response.status_code == 200
    assert not patch_route.called


def test_bootstrap_schema_patches_then_becomes_noop(client: TestClient, load_fixture) -> None:  # type: ignore[no-untyped-def]
    _put_notion(client)
    data_source = load_fixture("notion/data_source.json")
    with respx.mock(base_url=NOTION_BASE, assert_all_called=False) as router:
        get_route = router.get(f"/v1/data_sources/{DATA_SOURCE_ID}")
        get_route.mock(return_value=httpx.Response(200, json=data_source))
        patch_route = router.patch(f"/v1/data_sources/{DATA_SOURCE_ID}").mock(
            return_value=httpx.Response(200, json={"object": "data_source", "id": DATA_SOURCE_ID})
        )

        first = client.post("/api/integrations/notion/bootstrap-schema")
        assert first.status_code == 200
        assert first.json()["patched"] is True
        assert set(first.json()["properties"]) == {"封面", "自动化状态", "失败原因", "状态"}
        assert len(patch_route.calls) == 1

        patch_payload = json.loads(patch_route.calls[0].request.content)
        status_options = patch_payload["properties"]["状态"]["status"]["options"]
        assert [option["name"] for option in status_options] == ["选题池", "撰写中", "已发布", "待发布", "已交付"]

        merged = _merge_properties(data_source, patch_payload["properties"])
        get_route.mock(return_value=httpx.Response(200, json=merged))
        second = client.post("/api/integrations/notion/bootstrap-schema")

    assert second.status_code == 200
    assert second.json() == {"patched": False, "properties": []}
    assert len(patch_route.calls) == 1


def test_bootstrap_schema_without_integration_returns_404(client: TestClient) -> None:
    response = client.post("/api/integrations/notion/bootstrap-schema")

    assert response.status_code == 404
    assert response.json()["code"] == "INTEGRATION_NOT_FOUND"


def test_bootstrap_schema_without_secret_returns_409(client: TestClient) -> None:
    _put_notion(client, with_secret=False)

    response = client.post("/api/integrations/notion/bootstrap-schema")

    assert response.status_code == 409
    assert response.json()["code"] == "NOTION_SECRET_NOT_CONFIGURED"


def test_bootstrap_schema_config_error_returns_400_redacted(client: TestClient, load_fixture) -> None:  # type: ignore[no-untyped-def]
    _put_notion(client)
    with respx.mock(base_url=NOTION_BASE, assert_all_called=False) as router:
        router.get(f"/v1/data_sources/{DATA_SOURCE_ID}").mock(
            return_value=httpx.Response(403, json={"message": f"token {TOKEN} lacks access"})
        )
        response = client.post("/api/integrations/notion/bootstrap-schema")

    assert response.status_code == 400
    assert response.json()["code"] == "NOTION_CONFIG_INVALID"
    assert TOKEN not in response.text
