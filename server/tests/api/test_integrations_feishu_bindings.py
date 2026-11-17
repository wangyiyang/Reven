"""飞书资源绑定管理 API 集成测试：CRUD、启用唯一性、探针各阶段分支。

探针出站流量经 ProviderClients 注入的 MockTransport stub（feishu_transport seam），
不碰真实网络；每个用例可替换 stub.handler 定制飞书侧响应。
"""

import asyncio
import base64
import contextlib
import json
import os
from collections.abc import AsyncIterator, Callable, Iterator

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from reven.api.routes.integrations import router as integrations_router
from reven.config import Settings
from reven.db import create_session_factory
from reven.integrations.credentials import IntegrationCredentials
from reven.provider_clients import ProviderClients
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

TEST_MASTER_KEY = base64.urlsafe_b64encode(b"t" * 32).decode()
APP_ID = "cli_binding_test"
APP_SECRET = "binding-test-secret-value"
APP_TOKEN = "bascn_target_app"
TABLE_ID = "tbl_target"
TABLE_URL = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}"

REQUIRED_FIELD_ITEMS = [
    {"field_id": f"fld_{index}", "field_name": name, "type": field_type}
    for index, (name, field_type) in enumerate(
        [
            ("标题", 1),
            ("摘要", 1),
            ("来源", 1),
            ("发布时间", 5),
            ("原文链接", 15),
            ("状态", 3),
            ("命中关键词", 1),
            ("入库日期", 5),
            ("去重键", 1),
        ]
    )
]


class _FeishuApiStub:
    """可分派到每个用例自定义 handler 的 MockTransport 处理器。"""

    def __init__(self) -> None:
        self.handler: Callable[[httpx.Request], httpx.Response] | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if "/auth/" in request.url.path:
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "t-probe-token"})
        if self.handler is None:
            return httpx.Response(500, json={"code": 500, "msg": "unstubbed"})
        return self.handler(request)


class _BindingRig:
    def __init__(self, client: TestClient, stub: _FeishuApiStub) -> None:
        self.client = client
        self.stub = stub

    def put_feishu_bot(self, *, enabled: bool = True, with_secret: bool = True) -> None:
        payload: dict[str, object] = {
            "public_config": {"whitelist_open_ids": ["ou_boss"], "enabled": enabled},
        }
        if with_secret:
            payload["secret"] = {"app_id": APP_ID, "app_secret": APP_SECRET}
        response = self.client.put("/api/integrations/feishu_bot", json=payload)
        assert response.status_code == 200, response.text

    def create_binding(self, **overrides: object) -> httpx.Response:
        payload: dict[str, object] = {
            "resource_type": "bitable",
            "purpose": "rss_candidates",
            "config": {"app_token": APP_TOKEN, "table_id": TABLE_ID},
        }
        payload.update(overrides)
        return self.client.post("/api/integrations/feishu_bot/bindings", json=payload)


def _probe_success_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("/fields"):
        return httpx.Response(200, json={"code": 0, "data": {"items": REQUIRED_FIELD_ITEMS, "has_more": False}})
    if path.endswith("/records/search"):
        return httpx.Response(200, json={"code": 0, "data": {"items": [], "has_more": False}})
    if path.endswith("/records/batch_create"):
        return httpx.Response(200, json={"code": 0, "data": {"records": [{"record_id": "rec_probe", "fields": {}}]}})
    if path.endswith("/records/batch_delete"):
        return httpx.Response(200, json={"code": 0, "data": {"records": [{"record_id": "rec_probe", "deleted": True}]}})
    return httpx.Response(500, json={"code": 500, "msg": "unexpected"})


@pytest.fixture
def rig() -> Iterator[_BindingRig]:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("TEST_DATABASE_URL is not set, skipping API tests")
    settings = Settings(
        database_url=database_url,
        reven_master_key=TEST_MASTER_KEY,
        reven_admin_password="test-admin-password",
        siliconflow_api_key=None,
        agent_api_key=None,
        _env_file=None,
    )
    stub = _FeishuApiStub()

    async def reset() -> None:
        engine = create_async_engine(database_url)
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text("TRUNCATE feishu_resource_bindings, integrations RESTART IDENTITY CASCADE")
                )
        finally:
            await engine.dispose()

    asyncio.run(reset())

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        session_factory = create_session_factory(settings)
        credentials = IntegrationCredentials(session_factory, settings)
        app.state.session_factory = session_factory
        app.state.integration_credentials = credentials
        app.state.provider_clients = ProviderClients(credentials, settings, feishu_transport=httpx.MockTransport(stub))
        yield
        engine = session_factory.kw.get("bind")
        if isinstance(engine, AsyncEngine):
            await engine.dispose()

    app = FastAPI(lifespan=lifespan)
    app.include_router(integrations_router)
    with TestClient(app, raise_server_exceptions=True) as test_client:
        yield _BindingRig(test_client, stub)


# --- CRUD ---


def test_create_binding_persists_and_lists(rig: _BindingRig) -> None:
    rig.put_feishu_bot()

    created = rig.create_binding()

    assert created.status_code == 200, created.text
    body = created.json()
    assert body["resource_type"] == "bitable"
    assert body["purpose"] == "rss_candidates"
    assert body["config"] == {"app_token": APP_TOKEN, "table_id": TABLE_ID}
    assert body["enabled"] is False
    assert body["id"]

    listed = rig.client.get("/api/integrations/feishu_bot/bindings")
    assert listed.status_code == 200
    items = listed.json()
    assert len(items) == 1
    assert items[0]["id"] == body["id"]


def test_create_binding_requires_configured_and_enabled_feishu_bot(rig: _BindingRig) -> None:
    missing = rig.create_binding()
    assert missing.status_code == 409
    assert missing.json()["code"] == "FEISHU_BOT_NOT_ENABLED"

    rig.put_feishu_bot(enabled=False)
    disabled = rig.create_binding()
    assert disabled.status_code == 409
    assert disabled.json()["code"] == "FEISHU_BOT_NOT_ENABLED"


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"app_token": APP_TOKEN},
        {"app_token": "", "table_id": TABLE_ID},
        {"app_token": APP_TOKEN, "table_id": TABLE_ID, "extra": "x"},
        {"app_token": "has space", "table_id": TABLE_ID},
    ],
)
def test_create_binding_rejects_invalid_config_schema(rig: _BindingRig, config: dict[str, str]) -> None:
    rig.put_feishu_bot()

    response = rig.create_binding(config=config)

    assert response.status_code == 422


@pytest.mark.parametrize(
    "overrides",
    [
        {"resource_type": "wiki"},
        {"purpose": "doc_sync"},
    ],
)
def test_create_binding_rejects_unknown_type_or_purpose(rig: _BindingRig, overrides: dict[str, str]) -> None:
    rig.put_feishu_bot()

    response = rig.create_binding(**overrides)

    assert response.status_code == 422


def test_update_binding_config(rig: _BindingRig) -> None:
    rig.put_feishu_bot()
    binding_id = rig.create_binding().json()["id"]

    updated = rig.client.put(
        f"/api/integrations/feishu_bot/bindings/{binding_id}",
        json={"config": {"app_token": "bascn_new", "table_id": "tbl_new"}},
    )

    assert updated.status_code == 200
    assert updated.json()["config"] == {"app_token": "bascn_new", "table_id": "tbl_new"}
    assert updated.json()["enabled"] is False


def test_update_unknown_binding_returns_404(rig: _BindingRig) -> None:
    rig.put_feishu_bot()

    response = rig.client.put(
        "/api/integrations/feishu_bot/bindings/00000000-0000-0000-0000-000000000000",
        json={"config": {"app_token": "bascn_new", "table_id": "tbl_new"}},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "BINDING_NOT_FOUND"


def test_enable_conflict_returns_409_until_other_disabled(rig: _BindingRig) -> None:
    rig.put_feishu_bot()
    first = rig.create_binding().json()["id"]
    second = rig.create_binding(config={"app_token": "bascn_two", "table_id": "tbl_two"}).json()["id"]

    assert rig.client.post(f"/api/integrations/feishu_bot/bindings/{first}/enable").status_code == 200

    conflict = rig.client.post(f"/api/integrations/feishu_bot/bindings/{second}/enable")
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "BINDING_PURPOSE_CONFLICT"

    assert rig.client.post(f"/api/integrations/feishu_bot/bindings/{first}/disable").status_code == 200
    enabled = rig.client.post(f"/api/integrations/feishu_bot/bindings/{second}/enable")
    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True


def test_create_enabled_binding_conflicts_with_existing_enabled(rig: _BindingRig) -> None:
    rig.put_feishu_bot()
    assert rig.create_binding(enabled=True).status_code == 200

    conflict = rig.create_binding(config={"app_token": "bascn_two", "table_id": "tbl_two"}, enabled=True)

    assert conflict.status_code == 409
    assert conflict.json()["code"] == "BINDING_PURPOSE_CONFLICT"


def test_delete_binding(rig: _BindingRig) -> None:
    rig.put_feishu_bot()
    binding_id = rig.create_binding().json()["id"]

    deleted = rig.client.delete(f"/api/integrations/feishu_bot/bindings/{binding_id}")

    assert deleted.status_code == 204
    assert rig.client.get("/api/integrations/feishu_bot/bindings").json() == []

    again = rig.client.delete(f"/api/integrations/feishu_bot/bindings/{binding_id}")
    assert again.status_code == 404


# --- 绑定测试探针 ---


def test_probe_success_covers_all_stages(rig: _BindingRig) -> None:
    rig.put_feishu_bot()
    binding_id = rig.create_binding(enabled=True).json()["id"]
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _probe_success_handler(request)

    rig.stub.handler = handler

    response = rig.client.post(f"/api/integrations/feishu_bot/bindings/{binding_id}/test")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert body["failed_stage"] is None
    assert [(stage["stage"], stage["success"]) for stage in body["stages"]] == [
        ("fields", True),
        ("search", True),
        ("create", True),
        ("delete", True),
    ]
    paths = [request.url.path for request in seen]
    assert paths == [
        f"/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/fields",
        f"/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records/search",
        f"/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records/batch_create",
        f"/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records/batch_delete",
    ]
    assert all(request.headers["authorization"] == "Bearer t-probe-token" for request in seen)
    create_body = json.loads(seen[2].content)
    assert create_body["records"][0]["fields"]["去重键"] == create_body["records"][0]["client_token"]
    delete_body = json.loads(seen[3].content)
    assert delete_body == {"records": ["rec_probe"]}
    assert APP_SECRET not in response.text


def test_probe_missing_field_fails_at_fields_stage(rig: _BindingRig) -> None:
    rig.put_feishu_bot()
    binding_id = rig.create_binding().json()["id"]
    called: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        called.append(request.url.path)
        items = [item for item in REQUIRED_FIELD_ITEMS if item["field_name"] != "去重键"]
        return httpx.Response(200, json={"code": 0, "data": {"items": items, "has_more": False}})

    rig.stub.handler = handler

    body = rig.client.post(f"/api/integrations/feishu_bot/bindings/{binding_id}/test").json()

    assert body["success"] is False
    assert body["failed_stage"] == "fields"
    assert [stage["stage"] for stage in body["stages"]] == ["fields"]
    assert "缺少字段「去重键」" in body["stages"][0]["message"]
    assert len(called) == 1  # 未进入 search/create/delete


def test_probe_field_type_mismatch_fails_at_fields_stage(rig: _BindingRig) -> None:
    rig.put_feishu_bot()
    binding_id = rig.create_binding().json()["id"]

    def handler(request: httpx.Request) -> httpx.Response:
        items = [{**item, "type": 1} if item["field_name"] == "原文链接" else item for item in REQUIRED_FIELD_ITEMS]
        return httpx.Response(200, json={"code": 0, "data": {"items": items, "has_more": False}})

    rig.stub.handler = handler

    body = rig.client.post(f"/api/integrations/feishu_bot/bindings/{binding_id}/test").json()

    assert body["failed_stage"] == "fields"
    assert "「原文链接」应为超链接" in body["stages"][0]["message"]


def test_probe_search_failure(rig: _BindingRig) -> None:
    rig.put_feishu_bot()
    binding_id = rig.create_binding().json()["id"]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/records/search"):
            return httpx.Response(200, json={"code": 1254290, "msg": f"secret {APP_SECRET} t-probe-token"})
        return _probe_success_handler(request)

    rig.stub.handler = handler

    response = rig.client.post(f"/api/integrations/feishu_bot/bindings/{binding_id}/test")

    body = response.json()
    assert body["failed_stage"] == "search"
    assert [stage["stage"] for stage in body["stages"]] == ["fields", "search"]
    assert "code=1254290" in body["stages"][1]["message"]
    assert APP_SECRET not in response.text
    assert "t-probe-token" not in response.text


def test_probe_create_failure(rig: _BindingRig) -> None:
    rig.put_feishu_bot()
    binding_id = rig.create_binding().json()["id"]
    called: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        called.append(request.url.path)
        if request.url.path.endswith("/records/batch_create"):
            return httpx.Response(200, json={"code": 1254607, "msg": "field value invalid"})
        return _probe_success_handler(request)

    rig.stub.handler = handler

    body = rig.client.post(f"/api/integrations/feishu_bot/bindings/{binding_id}/test").json()

    assert body["failed_stage"] == "create"
    assert [stage["stage"] for stage in body["stages"]] == ["fields", "search", "create"]
    assert not any(path.endswith("/records/batch_delete") for path in called)


def test_probe_delete_failure_of_external_synced_table_fails_overall(rig: _BindingRig) -> None:
    rig.put_feishu_bot()
    binding_id = rig.create_binding().json()["id"]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/records/batch_delete"):
            return httpx.Response(200, json={"code": 1254061, "msg": "synced table readonly"})
        return _probe_success_handler(request)

    rig.stub.handler = handler

    body = rig.client.post(f"/api/integrations/feishu_bot/bindings/{binding_id}/test").json()

    assert body["success"] is False
    assert body["failed_stage"] == "delete"
    assert [stage["stage"] for stage in body["stages"]] == ["fields", "search", "create", "delete"]
    assert "外部同步表" in body["stages"][3]["message"]


def test_probe_unknown_binding_returns_404(rig: _BindingRig) -> None:
    rig.put_feishu_bot()

    response = rig.client.post("/api/integrations/feishu_bot/bindings/00000000-0000-0000-0000-000000000000/test")

    assert response.status_code == 404
    assert response.json()["code"] == "BINDING_NOT_FOUND"


def test_probe_without_credentials_reports_unavailable(rig: _BindingRig) -> None:
    rig.put_feishu_bot(with_secret=False)
    binding_id = rig.create_binding().json()["id"]

    response = rig.client.post(f"/api/integrations/feishu_bot/bindings/{binding_id}/test")

    body = response.json()
    assert response.status_code == 200
    assert body["success"] is False
    assert body["failed_stage"] is None
    assert body["stages"] == []
    assert body["message"] == "飞书应用机器人未启用或凭证不可用"
