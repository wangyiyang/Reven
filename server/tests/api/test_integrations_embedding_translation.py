"""机翻与 Embedding 集成卡片的 API 级测试：PUT/GET/掩码 hint/DELETE/连接测试。"""

import httpx
import respx
from fastapi.testclient import TestClient

EMBEDDING_BASE = "https://api.siliconflow.cn"


def _translation_payload(secret: dict[str, str] | None = None) -> dict[str, object]:
    payload: dict[str, object] = {"public_config": {"priority": 1, "enabled": True}}
    if secret is not None:
        payload["secret"] = secret
    return payload


def _embedding_payload(api_key: str | None = None) -> dict[str, object]:
    payload: dict[str, object] = {"public_config": {"base_url": EMBEDDING_BASE, "model": "BAAI/bge-m3"}}
    if api_key is not None:
        payload["secret"] = {"api_key": api_key}
    return payload


def test_translation_providers_roundtrip_with_masked_hint(client: TestClient) -> None:
    cases = [
        ("translate_baidu", {"app_id": "2026082500001", "app_key": "baidu-key-6666"}, "已配置 · ****6666"),
        (
            "translate_aliyun",
            {"access_key_id": "LTAI5tExample", "access_key_secret": "aliyun-secret-7777"},
            "已配置 · ****7777",
        ),
    ]
    for provider, secret, hint in cases:
        response = client.put(f"/api/integrations/{provider}", json=_translation_payload(secret))

        assert response.status_code == 200, provider
        body = response.json()
        assert body["provider"] == provider
        assert body["public_config"] == {"priority": 1, "enabled": True}
        assert body["secret_configured"] is True
        assert body["secret_hint"] == hint
        for value in secret.values():
            assert value not in response.text

        detail = client.get(f"/api/integrations/{provider}")
        assert detail.status_code == 200
        assert detail.json() == body

        deleted = client.delete(f"/api/integrations/{provider}/secret")
        assert deleted.status_code == 200
        assert deleted.json()["secret_configured"] is False
        assert deleted.json()["secret_hint"] is None


def test_translation_public_config_validation(client: TestClient) -> None:
    bad_priority = client.put(
        "/api/integrations/translate_baidu",
        json={"public_config": {"priority": 0}, "secret": {"app_id": "a", "app_key": "b"}},
    )
    assert bad_priority.status_code == 422

    extra_field = client.put(
        "/api/integrations/translate_baidu",
        json={
            "public_config": {"priority": 1, "region": "cn"},
            "secret": {"app_id": "a", "app_key": "b"},
        },
    )
    assert extra_field.status_code == 422

    missing_secret_field = client.put(
        "/api/integrations/translate_aliyun",
        json={"public_config": {"priority": 1}, "secret": {"access_key_id": "a"}},
    )
    assert missing_secret_field.status_code == 422


def test_embedding_provider_roundtrip_with_masked_hint(client: TestClient) -> None:
    response = client.put("/api/integrations/embedding", json=_embedding_payload("sk-siliconflow-abcd"))

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "embedding"
    assert body["public_config"] == {"base_url": EMBEDDING_BASE, "model": "BAAI/bge-m3"}
    assert body["secret_hint"] == "已配置 · ****abcd"
    assert "sk-siliconflow-abcd" not in response.text

    deleted = client.delete("/api/integrations/embedding/secret")
    assert deleted.status_code == 200
    assert deleted.json()["secret_configured"] is False


def test_embedding_base_url_must_be_https_origin(client: TestClient) -> None:
    bad_scheme = client.put(
        "/api/integrations/embedding",
        json={"public_config": {"base_url": "http://embedding.example.com"}, "secret": {"api_key": "sk-test"}},
    )
    assert bad_scheme.status_code == 422

    with_path = client.put(
        "/api/integrations/embedding",
        json={"public_config": {"base_url": "https://embedding.example.com/v1"}, "secret": {"api_key": "sk-test"}},
    )
    assert with_path.status_code == 422

    localhost = client.put(
        "/api/integrations/embedding",
        json={"public_config": {"base_url": "http://localhost:8080"}, "secret": {"api_key": "sk-test"}},
    )
    assert localhost.status_code == 200
    assert localhost.json()["public_config"]["base_url"] == "http://localhost:8080"

    trailing_slash = client.put(
        "/api/integrations/embedding",
        json={"public_config": {"base_url": "https://embedding.example.com/"}, "secret": {"api_key": "sk-test"}},
    )
    assert trailing_slash.status_code == 200
    assert trailing_slash.json()["public_config"]["base_url"] == "https://embedding.example.com"


def test_tencent_translation_routes_are_unknown(client: TestClient) -> None:
    requests = (
        client.get("/api/integrations/translate_tencent"),
        client.put("/api/integrations/translate_tencent", json=_translation_payload()),
        client.delete("/api/integrations/translate_tencent/secret"),
        client.post("/api/integrations/translate_tencent/test"),
    )

    for response in requests:
        assert response.status_code == 404
        assert response.json()["code"] == "INTEGRATION_PROVIDER_UNKNOWN"


def test_baidu_and_aliyun_connection_tests_remain_registered(client: TestClient) -> None:
    client.put(
        "/api/integrations/translate_baidu",
        json=_translation_payload({"app_id": "baidu-app-id", "app_key": "baidu-app-key"}),
    )
    with respx.mock(base_url="https://fanyi-api.baidu.com") as router:
        router.get("/api/trans/vip/translate").mock(
            return_value=httpx.Response(200, json={"trans_result": [{"src": "hello", "dst": "你好"}]})
        )
        baidu = client.post("/api/integrations/translate_baidu/test")

    client.put(
        "/api/integrations/translate_aliyun",
        json=_translation_payload({"access_key_id": "aliyun-access-id", "access_key_secret": "aliyun-access-secret"}),
    )
    with respx.mock(base_url="https://mt.cn-hangzhou.aliyuncs.com") as router:
        router.get("/").mock(return_value=httpx.Response(200, json={"Code": "200", "Data": {"Translated": "你好"}}))
        aliyun = client.post("/api/integrations/translate_aliyun/test")

    for response in (baidu, aliyun):
        assert response.status_code == 200
        assert response.json()["connection_status"] == "连接正常"
        assert response.json()["last_latency_ms"] is not None
    assert "baidu-app-key" not in baidu.text
    assert "aliyun-access-secret" not in aliyun.text


def test_embedding_connection_test_via_api(client: TestClient) -> None:
    client.put("/api/integrations/embedding", json=_embedding_payload("sk-siliconflow-abcd"))

    embedding_body = {
        "object": "list",
        "model": "BAAI/bge-m3",
        "data": [{"object": "embedding", "index": 0, "embedding": [0.5] * 1024}],
    }
    with respx.mock(base_url=EMBEDDING_BASE) as router:
        request = router.post("/v1/embeddings").mock(return_value=httpx.Response(200, json=embedding_body))
        response = client.post("/api/integrations/embedding/test")

    assert response.status_code == 200
    body = response.json()
    assert body["connection_status"] == "连接正常"
    assert body["last_latency_ms"] is not None
    assert request.calls[0].request.headers["authorization"] == "Bearer sk-siliconflow-abcd"
    assert "sk-siliconflow-abcd" not in response.text


def test_embedding_connection_test_without_secret(client: TestClient) -> None:
    client.put("/api/integrations/embedding", json=_embedding_payload())

    response = client.post("/api/integrations/embedding/test")

    assert response.status_code == 200
    body = response.json()
    assert body["connection_status"] == "连接失败"
    assert body["last_error"] == "Embedding API Key 尚未配置"
