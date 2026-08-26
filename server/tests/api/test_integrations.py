import asyncio
import os

from fastapi.testclient import TestClient
from reven.integrations.models import Integration
from reven.integrations.service import (
    ConnectionTestResult,
    register_connection_test_adapter,
    unregister_connection_test_adapter,
)
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

DATA_SOURCE_ID = "11111111-1111-1111-1111-111111111111"
DATABASE_ID = "22222222-2222-2222-2222-222222222222"


def _notion_payload(token: str | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "public_config": {"data_source_id": DATA_SOURCE_ID, "database_id": DATABASE_ID},
    }
    if token is not None:
        payload["secret"] = {"token": token}
    return payload


def _fetch_integration(provider: str) -> Integration | None:
    async def _query() -> Integration | None:
        engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                return await session.scalar(select(Integration).where(Integration.provider == provider))
        finally:
            await engine.dispose()

    return asyncio.run(_query())


def _corrupt_encrypted_secret(provider: str) -> None:
    async def _update() -> None:
        engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text("UPDATE integrations SET encrypted_secret = 'v1:corrupted' WHERE provider = :provider"),
                    {"provider": provider},
                )
        finally:
            await engine.dispose()

    asyncio.run(_update())


def _insert_legacy_integration(provider: str, encrypted_secret: str) -> None:
    async def _insert() -> None:
        engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory.begin() as session:
                session.add(
                    Integration(
                        provider=provider,
                        public_config={"legacy_marker": "must-not-leak"},
                        encrypted_secret=encrypted_secret,
                    )
                )
        finally:
            await engine.dispose()

    asyncio.run(_insert())


def test_short_secret_hint_does_not_leak_plaintext(client: TestClient) -> None:
    response = client.put("/api/integrations/notion", json=_notion_payload("ab"))

    assert response.status_code == 200
    body = response.json()
    assert body["secret_configured"] is True
    assert body["secret_hint"] == "已配置 · ****"
    assert "ab" not in body["secret_hint"]


def test_integration_response_never_contains_secret(client: TestClient) -> None:
    response = client.put(
        "/api/integrations/notion",
        json={
            "public_config": {"data_source_id": DATA_SOURCE_ID, "database_id": DATABASE_ID},
            "secret": {"token": "notion-secret"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["secret_configured"] is True
    assert "notion-secret" not in response.text
    assert "encrypted_secret" not in body


def test_put_creates_integration_with_hint(client: TestClient) -> None:
    response = client.put("/api/integrations/notion", json=_notion_payload("ntn_0000aaaa"))

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "notion"
    assert body["public_config"] == {"data_source_id": DATA_SOURCE_ID, "database_id": DATABASE_ID}
    assert body["secret_configured"] is True
    assert body["secret_hint"] == "已配置 · ****aaaa"
    assert body["connection_status"] == "未测试"
    assert body["last_tested_at"] is None
    assert body["last_error"] is None


def test_put_replaces_secret_and_updates_hint(client: TestClient) -> None:
    client.put("/api/integrations/notion", json=_notion_payload("ntn_0000aaaa"))
    first = _fetch_integration("notion")
    assert first is not None

    response = client.put("/api/integrations/notion", json=_notion_payload("ntn_0000bbbb"))

    assert response.status_code == 200
    assert response.json()["secret_hint"] == "已配置 · ****bbbb"
    second = _fetch_integration("notion")
    assert second is not None
    assert second.encrypted_secret != first.encrypted_secret


def test_put_without_secret_preserves_ciphertext(client: TestClient) -> None:
    client.put("/api/integrations/notion", json=_notion_payload("ntn_0000aaaa"))
    first = _fetch_integration("notion")
    assert first is not None

    response = client.put("/api/integrations/notion", json=_notion_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["secret_configured"] is True
    assert body["secret_hint"] == "已配置 · ****aaaa"
    second = _fetch_integration("notion")
    assert second is not None
    assert second.encrypted_secret == first.encrypted_secret


def test_delete_secret_removes_ciphertext_and_hint(client: TestClient) -> None:
    client.put("/api/integrations/notion", json=_notion_payload("ntn_0000aaaa"))

    response = client.delete("/api/integrations/notion/secret")

    assert response.status_code == 200
    body = response.json()
    assert body["secret_configured"] is False
    assert body["secret_hint"] is None
    stored = _fetch_integration("notion")
    assert stored is not None
    assert stored.encrypted_secret is None
    assert "ntn_0000aaaa" not in response.text


def test_delete_secret_without_secret_returns_404(client: TestClient) -> None:
    client.put("/api/integrations/notion", json=_notion_payload())

    response = client.delete("/api/integrations/notion/secret")

    assert response.status_code == 404
    assert response.json()["code"] == "INTEGRATION_SECRET_NOT_CONFIGURED"


def test_get_list_and_detail_shapes(client: TestClient) -> None:
    client.put("/api/integrations/notion", json=_notion_payload("ntn_0000aaaa"))
    client.put(
        "/api/integrations/github",
        json={
            "public_config": {"owner": "octo-org", "repo": "octo_repo"},
            "secret": {"token": "github-token-1234"},
        },
    )

    list_response = client.get("/api/integrations")
    assert list_response.status_code == 200
    items = {item["provider"]: item for item in list_response.json()}
    assert set(items) == {"notion", "github"}
    notion = items["notion"]
    assert set(notion) == {
        "provider",
        "public_config",
        "secret_configured",
        "secret_hint",
        "connection_status",
        "last_tested_at",
        "last_error",
        "last_latency_ms",
    }
    assert items["github"]["secret_hint"] == "已配置 · ****1234"

    detail_response = client.get("/api/integrations/notion")
    assert detail_response.status_code == 200
    assert detail_response.json() == notion
    assert "ntn_0000aaaa" not in list_response.text
    assert "github-token-1234" not in list_response.text


def test_list_filters_unsupported_legacy_provider(client: TestClient) -> None:
    configured = client.put("/api/integrations/notion", json=_notion_payload("notion-secret"))
    assert configured.status_code == 200
    _insert_legacy_integration("translate_tencent", "legacy-ciphertext-must-not-leak")

    response = client.get("/api/integrations")

    assert response.status_code == 200
    assert [item["provider"] for item in response.json()] == ["notion"]
    assert "translate_tencent" not in response.text
    assert "legacy-ciphertext-must-not-leak" not in response.text
    assert "notion-secret" not in response.text


def test_get_missing_integration_returns_404(client: TestClient) -> None:
    response = client.get("/api/integrations/notion")

    assert response.status_code == 404
    assert response.json()["code"] == "INTEGRATION_NOT_FOUND"


def test_unknown_provider_is_rejected(client: TestClient) -> None:
    for method in ("get", "put", "delete"):
        url = "/api/integrations/gitlab" if method != "delete" else "/api/integrations/gitlab/secret"
        kwargs = {"json": _notion_payload()} if method == "put" else {}
        response = getattr(client, method)(url, **kwargs)

        assert response.status_code == 404
        assert response.json()["code"] == "INTEGRATION_PROVIDER_UNKNOWN"


def test_extra_fields_are_rejected(client: TestClient) -> None:
    payload = _notion_payload("ntn_0000aaaa")
    payload["public_config"]["unexpected"] = "x"  # type: ignore[index]

    response = client.put("/api/integrations/notion", json=payload)

    assert response.status_code == 422


def test_invalid_public_config_is_rejected(client: TestClient) -> None:
    bad_uuid = client.put(
        "/api/integrations/notion",
        json={"public_config": {"data_source_id": "not-a-uuid", "database_id": DATABASE_ID}},
    )
    assert bad_uuid.status_code == 422

    bad_slug = client.put(
        "/api/integrations/github",
        json={"public_config": {"owner": "bad owner!", "repo": "ok-repo"}},
    )
    assert bad_slug.status_code == 422

    bad_webhook = client.put(
        "/api/integrations/feishu",
        json={
            "public_config": {"name": "发布通知"},
            "secret": {"webhook_url": "https://evil.example.com/hook/abc"},
        },
    )
    assert bad_webhook.status_code == 422

    good_webhook = client.put(
        "/api/integrations/feishu",
        json={
            "public_config": {"name": "发布通知"},
            "secret": {"webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/abc-123"},
        },
    )
    assert good_webhook.status_code == 200
    assert good_webhook.json()["secret_hint"] == "已配置 · ****-123"


def test_feishu_accepts_signing_secret_without_exposing_it(client: TestClient) -> None:
    response = client.put(
        "/api/integrations/feishu",
        json={
            "public_config": {"name": "发布通知"},
            "secret": {
                "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/abc-123",
                "signing_secret": "feishu-signing-secret",
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["secret_hint"] == "已配置 · ****-123"
    assert "feishu-signing-secret" not in response.text


def test_connection_test_without_adapter_returns_503(client: TestClient) -> None:
    # notion 已接入真实适配器；wechat 尚未接入，用于验证无适配器时的行为
    client.put(
        "/api/integrations/wechat",
        json={"public_config": {"app_id": "wx0000abcd"}, "secret": {"app_secret": "wechat-secret"}},
    )

    response = client.post("/api/integrations/wechat/test")

    assert response.status_code == 503
    assert response.json()["code"] == "CONNECTION_TEST_UNAVAILABLE"


def test_connection_test_with_adapter_updates_status(client: TestClient) -> None:
    async def ok_adapter(public_config: dict[str, object], secrets: dict[str, str] | None) -> ConnectionTestResult:
        assert secrets == {"token": "ntn_0000aaaa"}
        return ConnectionTestResult(success=True)

    register_connection_test_adapter("notion", ok_adapter)
    try:
        client.put("/api/integrations/notion", json=_notion_payload("ntn_0000aaaa"))
        response = client.post("/api/integrations/notion/test")

        assert response.status_code == 200
        body = response.json()
        assert body["connection_status"] == "连接正常"
        assert body["last_tested_at"] is not None

        updated = client.put("/api/integrations/notion", json=_notion_payload())
        assert updated.json()["connection_status"] == "未测试"
        assert updated.json()["last_tested_at"] is None
    finally:
        unregister_connection_test_adapter("notion")


def test_connection_test_failure_is_redacted(client: TestClient) -> None:
    async def failing_adapter(public_config: dict[str, object], secrets: dict[str, str] | None) -> ConnectionTestResult:
        raise RuntimeError("鉴权失败：token ntn_0000aaaa 无效")

    register_connection_test_adapter("notion", failing_adapter)
    try:
        client.put("/api/integrations/notion", json=_notion_payload("ntn_0000aaaa"))
        response = client.post("/api/integrations/notion/test")

        assert response.status_code == 200
        body = response.json()
        assert body["connection_status"] == "连接失败"
        assert body["last_error"] is not None
        assert "ntn_0000aaaa" not in body["last_error"]
        assert "ntn_0000aaaa" not in response.text
    finally:
        unregister_connection_test_adapter("notion")


def test_connection_test_missing_integration_returns_404(client: TestClient) -> None:
    response = client.post("/api/integrations/wechat/test")

    assert response.status_code == 404
    assert response.json()["code"] == "INTEGRATION_NOT_FOUND"


def test_connection_test_with_corrupted_secret_returns_domain_error(client: TestClient) -> None:
    async def ok_adapter(public_config: dict[str, object], secrets: dict[str, str] | None) -> ConnectionTestResult:
        return ConnectionTestResult(success=True)

    register_connection_test_adapter("notion", ok_adapter)
    try:
        client.put("/api/integrations/notion", json=_notion_payload("ntn_0000aaaa"))
        _corrupt_encrypted_secret("notion")

        response = client.post("/api/integrations/notion/test")

        assert response.status_code == 500
        assert response.json()["code"] == "INTEGRATION_SECRET_INVALID"
        assert "ntn_0000aaaa" not in response.text
    finally:
        unregister_connection_test_adapter("notion")


def test_connection_test_persists_latency_and_response_exposes_it(client: TestClient) -> None:
    async def ok_adapter(public_config: dict[str, object], secrets: dict[str, str] | None) -> ConnectionTestResult:
        return ConnectionTestResult(success=True, latency_ms=87)

    register_connection_test_adapter("notion", ok_adapter)
    try:
        client.put("/api/integrations/notion", json=_notion_payload("ntn_0000aaaa"))
        assert client.get("/api/integrations/notion").json()["last_latency_ms"] is None

        response = client.post("/api/integrations/notion/test")

        assert response.status_code == 200
        assert response.json()["last_latency_ms"] == 87
        stored = _fetch_integration("notion")
        assert stored is not None
        assert stored.last_latency_ms == 87

        updated = client.put("/api/integrations/notion", json=_notion_payload())
        assert updated.json()["last_latency_ms"] is None
    finally:
        unregister_connection_test_adapter("notion")


def test_connection_test_failure_clears_latency(client: TestClient) -> None:
    async def ok_adapter(public_config: dict[str, object], secrets: dict[str, str] | None) -> ConnectionTestResult:
        return ConnectionTestResult(success=True, latency_ms=87)

    async def failing_adapter(public_config: dict[str, object], secrets: dict[str, str] | None) -> ConnectionTestResult:
        return ConnectionTestResult(success=False, message="网络不可达")

    register_connection_test_adapter("notion", ok_adapter)
    try:
        client.put("/api/integrations/notion", json=_notion_payload("ntn_0000aaaa"))
        assert client.post("/api/integrations/notion/test").json()["last_latency_ms"] == 87
        register_connection_test_adapter("notion", failing_adapter)

        response = client.post("/api/integrations/notion/test")

        assert response.status_code == 200
        body = response.json()
        assert body["connection_status"] == "连接失败"
        assert body["last_latency_ms"] is None
    finally:
        unregister_connection_test_adapter("notion")
