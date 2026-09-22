import asyncio
import base64
import os

import pytest
from fastapi.testclient import TestClient
from reven.api.routes.integrations import CONNECTION_TEST_ADAPTERS
from reven.integrations.models import Integration
from reven.integrations.providers import SUPPORTED_INTEGRATION_PROVIDERS
from reven.integrations.service import (
    ConnectionTestAdapter,
    ConnectionTestResult,
    IntegrationError,
    IntegrationService,
)
from reven.security.secrets import SecretBox
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_MASTER_KEY = base64.urlsafe_b64encode(b"t" * 32).decode()
EMBEDDING_CONFIG = {"base_url": "https://api.siliconflow.cn", "model": "BAAI/bge-m3"}


def _embedding_payload(token: str | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "public_config": dict(EMBEDDING_CONFIG),
    }
    if token is not None:
        payload["secret"] = {"api_key": token}
    return payload


def _secret_box() -> SecretBox:
    return SecretBox.from_base64(TEST_MASTER_KEY)


async def _seed_embedding_integration(db_session: AsyncSession) -> None:
    db_session.add(
        Integration(
            provider="embedding",
            public_config=dict(EMBEDDING_CONFIG),
            encrypted_secret=_secret_box().encrypt({"api_key": "embed_0000aaaa"}),
        )
    )
    await db_session.commit()


def _service(db_session: AsyncSession, adapters: dict[str, ConnectionTestAdapter]) -> IntegrationService:
    return IntegrationService(db_session, _secret_box(), adapters)


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
    response = client.put("/api/integrations/embedding", json=_embedding_payload("ab"))

    assert response.status_code == 200
    body = response.json()
    assert body["secret_configured"] is True
    assert body["secret_hint"] == "已配置 · ****"
    assert "ab" not in body["secret_hint"]


def test_integration_response_never_contains_secret(client: TestClient) -> None:
    response = client.put(
        "/api/integrations/embedding",
        json={
            "public_config": dict(EMBEDDING_CONFIG),
            "secret": {"api_key": "embedding-secret"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["secret_configured"] is True
    assert "embedding-secret" not in response.text
    assert "encrypted_secret" not in body


def test_put_creates_integration_with_hint(client: TestClient) -> None:
    response = client.put("/api/integrations/embedding", json=_embedding_payload("embed_0000aaaa"))

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "embedding"
    assert body["public_config"] == EMBEDDING_CONFIG
    assert body["secret_configured"] is True
    assert body["secret_hint"] == "已配置 · ****aaaa"
    assert body["connection_status"] == "未测试"
    assert body["last_tested_at"] is None
    assert body["last_error"] is None


def test_put_replaces_secret_and_updates_hint(client: TestClient) -> None:
    client.put("/api/integrations/embedding", json=_embedding_payload("embed_0000aaaa"))
    first = _fetch_integration("embedding")
    assert first is not None

    response = client.put("/api/integrations/embedding", json=_embedding_payload("embed_0000bbbb"))

    assert response.status_code == 200
    assert response.json()["secret_hint"] == "已配置 · ****bbbb"
    second = _fetch_integration("embedding")
    assert second is not None
    assert second.encrypted_secret != first.encrypted_secret


def test_put_without_secret_preserves_ciphertext(client: TestClient) -> None:
    client.put("/api/integrations/embedding", json=_embedding_payload("embed_0000aaaa"))
    first = _fetch_integration("embedding")
    assert first is not None

    response = client.put("/api/integrations/embedding", json=_embedding_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["secret_configured"] is True
    assert body["secret_hint"] == "已配置 · ****aaaa"
    second = _fetch_integration("embedding")
    assert second is not None
    assert second.encrypted_secret == first.encrypted_secret


def test_delete_secret_removes_ciphertext_and_hint(client: TestClient) -> None:
    client.put("/api/integrations/embedding", json=_embedding_payload("embed_0000aaaa"))

    response = client.delete("/api/integrations/embedding/secret")

    assert response.status_code == 200
    body = response.json()
    assert body["secret_configured"] is False
    assert body["secret_hint"] is None
    stored = _fetch_integration("embedding")
    assert stored is not None
    assert stored.encrypted_secret is None
    assert "embed_0000aaaa" not in response.text


def test_delete_secret_without_secret_returns_404(client: TestClient) -> None:
    client.put("/api/integrations/embedding", json=_embedding_payload())

    response = client.delete("/api/integrations/embedding/secret")

    assert response.status_code == 404
    assert response.json()["code"] == "INTEGRATION_SECRET_NOT_CONFIGURED"


def test_get_list_and_detail_shapes(client: TestClient) -> None:
    client.put("/api/integrations/embedding", json=_embedding_payload("embed_0000aaaa"))
    client.put(
        "/api/integrations/feishu_bot",
        json={
            "public_config": {"whitelist_open_ids": ["ou_owner"], "enabled": False},
            "secret": {"app_id": "cli_test", "app_secret": "test-secret-1234"},
        },
    )

    list_response = client.get("/api/integrations")
    assert list_response.status_code == 200
    items = {item["provider"]: item for item in list_response.json()}
    assert set(items) == {"embedding", "feishu_bot"}
    embedding = items["embedding"]
    assert set(embedding) == {
        "provider",
        "public_config",
        "secret_configured",
        "secret_hint",
        "connection_status",
        "last_tested_at",
        "last_error",
        "last_latency_ms",
    }
    assert items["feishu_bot"]["secret_hint"] == "已配置 · ****1234"

    detail_response = client.get("/api/integrations/embedding")
    assert detail_response.status_code == 200
    assert detail_response.json() == embedding
    assert "embed_0000aaaa" not in list_response.text
    assert "test-secret-1234" not in list_response.text


@pytest.mark.parametrize("provider", ["translate_tencent", "notion", "github", "wechat", "feishu"])
def test_list_filters_unsupported_legacy_provider(client: TestClient, provider: str) -> None:
    configured = client.put("/api/integrations/embedding", json=_embedding_payload("embedding-secret"))
    assert configured.status_code == 200
    _insert_legacy_integration(provider, "legacy-ciphertext-must-not-leak")

    response = client.get("/api/integrations")

    assert response.status_code == 200
    assert [item["provider"] for item in response.json()] == ["embedding"]
    assert provider not in response.text
    assert "legacy-ciphertext-must-not-leak" not in response.text
    assert "embedding-secret" not in response.text


def test_get_missing_integration_returns_404(client: TestClient) -> None:
    response = client.get("/api/integrations/embedding")

    assert response.status_code == 404
    assert response.json()["code"] == "INTEGRATION_NOT_FOUND"


def test_unknown_provider_is_rejected(client: TestClient) -> None:
    for method in ("get", "put", "delete"):
        url = "/api/integrations/gitlab" if method != "delete" else "/api/integrations/gitlab/secret"
        kwargs = {"json": _embedding_payload()} if method == "put" else {}
        response = getattr(client, method)(url, **kwargs)

        assert response.status_code == 404
        assert response.json()["code"] == "INTEGRATION_PROVIDER_UNKNOWN"


def test_extra_fields_are_rejected(client: TestClient) -> None:
    payload = _embedding_payload("embed_0000aaaa")
    payload["public_config"]["unexpected"] = "x"  # type: ignore[index]

    response = client.put("/api/integrations/embedding", json=payload)

    assert response.status_code == 422


def test_invalid_public_config_is_rejected(client: TestClient) -> None:
    invalid_origin = client.put(
        "/api/integrations/embedding",
        json={"public_config": {"base_url": "http://remote.example.com"}},
    )
    assert invalid_origin.status_code == 422


@pytest.mark.anyio
async def test_connection_test_without_adapter_returns_503(db_session: AsyncSession) -> None:
    await _seed_embedding_integration(db_session)
    service = _service(db_session, {})

    with pytest.raises(IntegrationError) as caught:
        await service.run_connection_test("embedding")

    assert caught.value.status_code == 503
    assert caught.value.code == "CONNECTION_TEST_UNAVAILABLE"


@pytest.mark.anyio
async def test_connection_test_with_adapter_updates_status(db_session: AsyncSession) -> None:
    async def ok_adapter(public_config: dict[str, object], secrets: dict[str, str] | None) -> ConnectionTestResult:
        assert secrets == {"api_key": "embed_0000aaaa"}
        return ConnectionTestResult(success=True)

    await _seed_embedding_integration(db_session)
    service = _service(db_session, {"embedding": ok_adapter})

    integration = await service.run_connection_test("embedding")

    assert integration.connection_status == "连接正常"
    assert integration.last_tested_at is not None

    updated = await service.upsert_integration(provider="embedding", public_config=dict(EMBEDDING_CONFIG), secret=None)
    assert updated.connection_status == "未测试"
    assert updated.last_tested_at is None


@pytest.mark.anyio
async def test_connection_test_failure_is_redacted(db_session: AsyncSession) -> None:
    async def failing_adapter(public_config: dict[str, object], secrets: dict[str, str] | None) -> ConnectionTestResult:
        raise RuntimeError("鉴权失败：token embed_0000aaaa 无效")

    await _seed_embedding_integration(db_session)
    service = _service(db_session, {"embedding": failing_adapter})

    integration = await service.run_connection_test("embedding")

    assert integration.connection_status == "连接失败"
    assert integration.last_error is not None
    assert "embed_0000aaaa" not in integration.last_error


def test_connection_test_missing_integration_returns_404(client: TestClient) -> None:
    response = client.post("/api/integrations/embedding/test")

    assert response.status_code == 404
    assert response.json()["code"] == "INTEGRATION_NOT_FOUND"


def test_connection_test_adapters_cover_all_supported_providers() -> None:
    assert set(CONNECTION_TEST_ADAPTERS) == set(SUPPORTED_INTEGRATION_PROVIDERS)


@pytest.mark.anyio
async def test_connection_test_with_corrupted_secret_returns_domain_error(db_session: AsyncSession) -> None:
    async def ok_adapter(public_config: dict[str, object], secrets: dict[str, str] | None) -> ConnectionTestResult:
        return ConnectionTestResult(success=True)

    db_session.add(
        Integration(
            provider="embedding",
            public_config=dict(EMBEDDING_CONFIG),
            encrypted_secret="v1:corrupted",
        )
    )
    await db_session.commit()
    service = _service(db_session, {"embedding": ok_adapter})

    with pytest.raises(IntegrationError) as caught:
        await service.run_connection_test("embedding")

    assert caught.value.status_code == 500
    assert caught.value.code == "INTEGRATION_SECRET_INVALID"
    assert "embed_0000aaaa" not in caught.value.message


@pytest.mark.anyio
async def test_connection_test_persists_latency_and_upsert_resets_it(db_session: AsyncSession) -> None:
    async def ok_adapter(public_config: dict[str, object], secrets: dict[str, str] | None) -> ConnectionTestResult:
        return ConnectionTestResult(success=True, latency_ms=87)

    await _seed_embedding_integration(db_session)
    service = _service(db_session, {"embedding": ok_adapter})
    assert (await service.get_integration("embedding")).last_latency_ms is None

    integration = await service.run_connection_test("embedding")

    assert integration.last_latency_ms == 87

    updated = await service.upsert_integration(provider="embedding", public_config=dict(EMBEDDING_CONFIG), secret=None)
    assert updated.last_latency_ms is None


@pytest.mark.anyio
async def test_connection_test_failure_clears_latency(db_session: AsyncSession) -> None:
    async def ok_adapter(public_config: dict[str, object], secrets: dict[str, str] | None) -> ConnectionTestResult:
        return ConnectionTestResult(success=True, latency_ms=87)

    async def failing_adapter(public_config: dict[str, object], secrets: dict[str, str] | None) -> ConnectionTestResult:
        return ConnectionTestResult(success=False, message="网络不可达")

    await _seed_embedding_integration(db_session)
    ok_service = _service(db_session, {"embedding": ok_adapter})
    assert (await ok_service.run_connection_test("embedding")).last_latency_ms == 87

    failing_service = _service(db_session, {"embedding": failing_adapter})
    integration = await failing_service.run_connection_test("embedding")

    assert integration.connection_status == "连接失败"
    assert integration.last_latency_ms is None
