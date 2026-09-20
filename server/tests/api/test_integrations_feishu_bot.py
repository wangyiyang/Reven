import json

import httpx
import respx
from fastapi.testclient import TestClient

TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
BOT_INFO_URL = "https://open.feishu.cn/open-apis/bot/v1/info"
APP_ID = "cli_a1b2c3d4e5"
APP_SECRET = "feishu-bot-secret-value"


def _credentials() -> dict[str, str]:
    return {"app_id": APP_ID, "app_secret": APP_SECRET}


def _payload(
    *,
    public_config: dict[str, object] | None = None,
    secret: dict[str, str] | None = None,
) -> dict[str, object]:
    default_config: dict[str, object] = {"whitelist_open_ids": ["ou_boss"], "enabled": True}
    payload: dict[str, object] = {
        "public_config": public_config if public_config is not None else default_config,
    }
    if secret is not None:
        payload["secret"] = secret
    return payload


def test_feishu_bot_put_stores_typed_config_and_redacts_secret(client: TestClient) -> None:
    response = client.put("/api/integrations/feishu_bot", json=_payload(secret=_credentials()))

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "feishu_bot"
    assert body["public_config"] == {"whitelist_open_ids": ["ou_boss"], "enabled": True}
    assert body["secret_configured"] is True
    assert body["secret_hint"] == "已配置 · ****alue"
    assert APP_ID not in response.text
    assert APP_SECRET not in response.text


def test_feishu_bot_public_config_defaults(client: TestClient) -> None:
    response = client.put("/api/integrations/feishu_bot", json=_payload(public_config={}, secret=_credentials()))

    assert response.status_code == 200
    assert response.json()["public_config"] == {"whitelist_open_ids": [], "enabled": False}


def test_feishu_bot_rejects_extra_fields(client: TestClient) -> None:
    extra_public = client.put(
        "/api/integrations/feishu_bot",
        json={"public_config": {"enabled": True, "unexpected": "x"}, "secret": _credentials()},
    )
    assert extra_public.status_code == 422

    extra_secret = client.put(
        "/api/integrations/feishu_bot",
        json={"public_config": {}, "secret": {**_credentials(), "webhook_url": "https://evil.example.com"}},
    )
    assert extra_secret.status_code == 422


def test_feishu_bot_rejects_blank_whitelist_entry(client: TestClient) -> None:
    response = client.put(
        "/api/integrations/feishu_bot",
        json=_payload(public_config={"whitelist_open_ids": ["ou_boss", ""]}, secret=_credentials()),
    )

    assert response.status_code == 422


def test_feishu_bot_connection_test_without_secret_fails(client: TestClient) -> None:
    configured = client.put("/api/integrations/feishu_bot", json=_payload())
    assert configured.status_code == 200

    response = client.post("/api/integrations/feishu_bot/test")

    assert response.status_code == 200
    body = response.json()
    assert body["connection_status"] == "连接失败"
    assert body["last_error"] == "飞书应用凭证尚未配置"


def test_feishu_bot_connection_test_rejects_invalid_credentials(client: TestClient) -> None:
    client.put("/api/integrations/feishu_bot", json=_payload(secret=_credentials()))

    with respx.mock(assert_all_called=True) as router:
        router.post(TOKEN_URL).mock(
            return_value=httpx.Response(200, json={"code": 99991663, "msg": "app_id or app_secret is wrong"})
        )
        response = client.post("/api/integrations/feishu_bot/test")

    assert response.status_code == 200
    body = response.json()
    assert body["connection_status"] == "连接失败"
    assert body["last_error"] == "飞书应用凭证无效"
    assert APP_SECRET not in response.text


def test_feishu_bot_connection_test_succeeds_with_tenant_token(client: TestClient) -> None:
    client.put("/api/integrations/feishu_bot", json=_payload(secret=_credentials()))

    with respx.mock(assert_all_called=True) as router:
        request = router.post(TOKEN_URL).mock(
            return_value=httpx.Response(200, json={"code": 0, "tenant_access_token": "t-token", "expire": 7200})
        )
        router.get(BOT_INFO_URL).mock(return_value=httpx.Response(200, json={"code": 0, "bot": {"app_name": "Reven"}}))
        response = client.post("/api/integrations/feishu_bot/test")

    assert response.status_code == 200
    assert response.json()["connection_status"] == "连接正常"
    payload = json.loads(request.calls[0].request.content)
    assert payload == {"app_id": APP_ID, "app_secret": APP_SECRET}


def test_feishu_bot_connection_test_network_failure_is_redacted(client: TestClient) -> None:
    client.put("/api/integrations/feishu_bot", json=_payload(secret=_credentials()))

    with respx.mock(assert_all_called=True) as router:
        router.post(TOKEN_URL).mock(side_effect=httpx.ConnectError(f"连接中断 {APP_SECRET}"))
        response = client.post("/api/integrations/feishu_bot/test")

    assert response.status_code == 200
    body = response.json()
    assert body["connection_status"] == "连接失败"
    assert "飞书应用连接失败（ConnectError）" in body["last_error"]
    assert APP_SECRET not in response.text


def test_feishu_bot_is_listed_after_configuration(client: TestClient) -> None:
    configured = client.put("/api/integrations/feishu_bot", json=_payload(secret=_credentials()))
    assert configured.status_code == 200

    response = client.get("/api/integrations")

    assert response.status_code == 200
    assert "feishu_bot" in [item["provider"] for item in response.json()]
    assert APP_SECRET not in response.text


class _FakeSupervisor:
    """记录 reload 调用次数的假 FeishuBotSupervisor。"""

    def __init__(self) -> None:
        self.reload_calls = 0

    def reload(self) -> None:
        self.reload_calls += 1


def test_put_feishu_bot_triggers_supervisor_reload(client: TestClient) -> None:
    supervisor = _FakeSupervisor()
    client.app.state.feishu_bot_supervisor = supervisor

    response = client.put("/api/integrations/feishu_bot", json=_payload(secret=_credentials()))

    assert response.status_code == 200
    assert supervisor.reload_calls == 1


def test_put_other_provider_does_not_trigger_reload(client: TestClient) -> None:
    supervisor = _FakeSupervisor()
    client.app.state.feishu_bot_supervisor = supervisor

    response = client.put(
        "/api/integrations/feishu",
        json={
            "public_config": {"name": "运营通知群"},
            "secret": {"webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/abc-def"},
        },
    )

    assert response.status_code == 200
    assert supervisor.reload_calls == 0


def test_put_feishu_bot_with_invalid_body_does_not_trigger_reload(client: TestClient) -> None:
    supervisor = _FakeSupervisor()
    client.app.state.feishu_bot_supervisor = supervisor

    response = client.put("/api/integrations/feishu_bot", json={"public_config": {"enabled": True, "unexpected": "x"}})

    assert response.status_code == 422
    assert supervisor.reload_calls == 0


def test_delete_feishu_bot_secret_triggers_reload(client: TestClient) -> None:
    supervisor = _FakeSupervisor()
    client.app.state.feishu_bot_supervisor = supervisor
    configured = client.put("/api/integrations/feishu_bot", json=_payload(secret=_credentials()))
    assert configured.status_code == 200
    assert supervisor.reload_calls == 1

    response = client.delete("/api/integrations/feishu_bot/secret")

    assert response.status_code == 200
    assert supervisor.reload_calls == 2
