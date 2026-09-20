import asyncio
import os

import httpx
import respx
from fastapi.testclient import TestClient
from reven.integrations.models import Integration
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

BASE_URL = "https://api.deepseek.com"


def _payload(api_key: str | None = None, **public_config: object) -> dict[str, object]:
    payload: dict[str, object] = {"public_config": public_config}
    if api_key is not None:
        payload["secret"] = {"api_key": api_key}
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


def test_put_applies_defaults_and_never_exposes_api_key(client: TestClient) -> None:
    response = client.put("/api/integrations/agent-llm", json=_payload("sk-deepseek-1234abcd"))

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "agent-llm"
    assert body["public_config"] == {"provider": "deepseek-official", "model": "deepseek-v4-flash"}
    assert body["secret_configured"] is True
    assert body["secret_hint"] == "已配置 · ****abcd"
    assert body["connection_status"] == "未测试"
    assert "sk-deepseek-1234abcd" not in response.text


def test_put_stores_full_config_and_encrypts_secret(client: TestClient) -> None:
    response = client.put(
        "/api/integrations/agent-llm",
        json=_payload("sk-deepseek-1234abcd", provider="deepseek-official", model="deepseek-v4-pro", base_url=BASE_URL),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["public_config"] == {
        "provider": "deepseek-official",
        "model": "deepseek-v4-pro",
        "base_url": BASE_URL,
    }

    detail = client.get("/api/integrations/agent-llm")
    assert detail.status_code == 200
    assert detail.json() == body
    assert "sk-deepseek-1234abcd" not in detail.text

    stored = _fetch_integration("agent-llm")
    assert stored is not None
    assert stored.encrypted_secret is not None
    assert "sk-deepseek-1234abcd" not in stored.encrypted_secret


def test_put_rejects_invalid_base_url(client: TestClient) -> None:
    plain_http = client.put(
        "/api/integrations/agent-llm",
        json=_payload("sk-deepseek-1234abcd", base_url="http://api.deepseek.com"),
    )
    assert plain_http.status_code == 422

    with_path = client.put(
        "/api/integrations/agent-llm",
        json=_payload("sk-deepseek-1234abcd", base_url=f"{BASE_URL}/v1"),
    )
    assert with_path.status_code == 422


def test_put_rejects_extra_fields(client: TestClient) -> None:
    response = client.put(
        "/api/integrations/agent-llm",
        json=_payload("sk-deepseek-1234abcd", provider="deepseek-official", unexpected="x"),
    )

    assert response.status_code == 422


def test_connection_test_without_api_key_fails(client: TestClient) -> None:
    client.put("/api/integrations/agent-llm", json=_payload())

    response = client.post("/api/integrations/agent-llm/test")

    assert response.status_code == 200
    body = response.json()
    assert body["connection_status"] == "连接失败"
    assert body["last_error"] == "Agent LLM API Key 尚未配置"


def test_connection_test_succeeds_with_api_key_only(client: TestClient) -> None:
    client.put("/api/integrations/agent-llm", json=_payload("sk-deepseek-1234abcd"))

    response = client.post("/api/integrations/agent-llm/test")

    assert response.status_code == 200
    assert response.json()["connection_status"] == "连接正常"


def test_connection_test_checks_base_url_reachability(client: TestClient) -> None:
    client.put("/api/integrations/agent-llm", json=_payload("sk-deepseek-1234abcd", base_url=BASE_URL))

    with respx.mock(assert_all_called=True) as router:
        router.get(BASE_URL).mock(return_value=httpx.Response(401))
        response = client.post("/api/integrations/agent-llm/test")

    assert response.status_code == 200
    body = response.json()
    assert body["connection_status"] == "连接正常"
    assert body["last_latency_ms"] is not None


def test_connection_test_reports_unreachable_base_url(client: TestClient) -> None:
    client.put("/api/integrations/agent-llm", json=_payload("sk-deepseek-1234abcd", base_url=BASE_URL))

    with respx.mock(assert_all_called=True) as router:
        router.get(BASE_URL).mock(side_effect=httpx.ConnectError("connection refused"))
        response = client.post("/api/integrations/agent-llm/test")

    assert response.status_code == 200
    body = response.json()
    assert body["connection_status"] == "连接失败"
    assert body["last_error"] is not None
    assert "不可达" in body["last_error"]
    assert "sk-deepseek-1234abcd" not in response.text
