"""agent-llm 多模型管理 API（#173）：models[] 写回、model_keys 合并、设默认、按 ref 测试。"""

import asyncio
import base64
import os

import httpx
import respx
from fastapi.testclient import TestClient
from reven.integrations.models import Integration
from reven.security.secrets import SecretBox
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

TEST_MASTER_KEY = base64.urlsafe_b64encode(b"t" * 32).decode()
BASE_URL = "https://api.deepseek.com"
SILICONFLOW_URL = "https://api.siliconflow.cn"

KEY_DEFAULT = "sk-default-0000aaaa"
KEY_PRO = "sk-pro-1111cdef"
KEY_QWEN = "sk-qwen-2222bbbb"
KEY_GHOST = "sk-ghost-3333cccc"

DEFAULT_REF = "deepseek-official/deepseek-v4-flash"
PRO_REF = "deepseek-official/deepseek-v4-pro"
QWEN_REF = "siliconflow/Qwen/Qwen3-32B"

PRO_ENTRY: dict[str, object] = {"provider": "deepseek-official", "model": "deepseek-v4-pro"}
QWEN_ENTRY: dict[str, object] = {
    "provider": "siliconflow",
    "model": "Qwen/Qwen3-32B",
    "base_url": SILICONFLOW_URL,
    "enabled": False,
}


def _payload(
    api_key: str | None = None,
    model_keys: dict[str, str] | None = None,
    **public_config: object,
) -> dict[str, object]:
    payload: dict[str, object] = {"public_config": public_config}
    secret: dict[str, object] = {}
    if api_key is not None:
        secret["api_key"] = api_key
    if model_keys is not None:
        secret["model_keys"] = model_keys
    if secret:
        payload["secret"] = secret
    return payload


def _stored_secrets(provider: str = "agent-llm") -> dict[str, str]:
    async def _query() -> dict[str, str]:
        engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                integration = await session.scalar(select(Integration).where(Integration.provider == provider))
            assert integration is not None and integration.encrypted_secret is not None
            return SecretBox.from_base64(TEST_MASTER_KEY).decrypt(integration.encrypted_secret)
        finally:
            await engine.dispose()

    return asyncio.run(_query())


def _put_with_models(client: TestClient, api_key: str, models: list[dict[str, object]]) -> dict[str, object]:
    response = client.put("/api/integrations/agent-llm", json=_payload(api_key, models=models))
    assert response.status_code == 200
    return response.json()  # type: ignore[no-any-return]


class _StubSupervisor:
    """feishu_bot_supervisor 替身：只提供 model_refs_in_use 接缝。"""

    def __init__(self, refs: frozenset[str]) -> None:
        self._refs = refs

    def model_refs_in_use(self) -> frozenset[str]:
        return self._refs


def test_models_roundtrip_with_enabled_flags(client: TestClient) -> None:
    body = _put_with_models(client, KEY_DEFAULT, [PRO_ENTRY, QWEN_ENTRY])

    assert body["public_config"]["models"] == [  # type: ignore[index]
        {"provider": "deepseek-official", "model": "deepseek-v4-pro", "enabled": True},
        QWEN_ENTRY,
    ]
    assert body["model_key_refs"] == []

    detail = client.get("/api/integrations/agent-llm")
    assert detail.status_code == 200
    assert detail.json() == body
    assert KEY_DEFAULT not in detail.text


def test_models_reject_duplicate_and_default_refs(client: TestClient) -> None:
    duplicated = client.put(
        "/api/integrations/agent-llm",
        json=_payload(KEY_DEFAULT, models=[PRO_ENTRY, PRO_ENTRY]),
    )
    assert duplicated.status_code == 422

    clashes_default = client.put(
        "/api/integrations/agent-llm",
        json=_payload(KEY_DEFAULT, models=[{"provider": "deepseek-official", "model": "deepseek-v4-flash"}]),
    )
    assert clashes_default.status_code == 422


def test_models_reject_invalid_entries(client: TestClient) -> None:
    plain_http = client.put(
        "/api/integrations/agent-llm",
        json=_payload(KEY_DEFAULT, models=[{"provider": "p", "model": "m", "base_url": "http://api.p.com"}]),
    )
    assert plain_http.status_code == 422

    extra_field = client.put(
        "/api/integrations/agent-llm",
        json=_payload(KEY_DEFAULT, models=[{"provider": "p", "model": "m", "region": "cn"}]),
    )
    assert extra_field.status_code == 422

    missing_model = client.put(
        "/api/integrations/agent-llm",
        json=_payload(KEY_DEFAULT, models=[{"provider": "p"}]),
    )
    assert missing_model.status_code == 422


def test_model_keys_merge_clear_and_prune(client: TestClient) -> None:
    response = client.put(
        "/api/integrations/agent-llm",
        json=_payload(
            KEY_DEFAULT,
            model_keys={PRO_REF: KEY_PRO, QWEN_REF: KEY_QWEN},
            models=[PRO_ENTRY, {**QWEN_ENTRY, "enabled": True}],
        ),
    )
    assert response.status_code == 200
    assert response.json()["model_key_refs"] == [PRO_REF, QWEN_REF]
    assert KEY_PRO not in response.text
    assert KEY_QWEN not in response.text
    assert KEY_DEFAULT not in response.text
    secrets = _stored_secrets()
    assert secrets["api_key"] == KEY_DEFAULT
    assert secrets[f"model_key:{PRO_REF}"] == KEY_PRO
    assert secrets[f"model_key:{QWEN_REF}"] == KEY_QWEN

    # 纯配置保存移除 QWEN 条目：api_key 与 PRO 独立 key 保留，QWEN 独立 key 被 prune
    saved = _put_with_models(client, KEY_DEFAULT, [PRO_ENTRY])
    assert saved["model_key_refs"] == [PRO_REF]
    secrets = _stored_secrets()
    assert f"model_key:{QWEN_REF}" not in secrets
    assert secrets["api_key"] == KEY_DEFAULT

    # 空串清除 PRO 独立 key（回落共用默认密钥）
    cleared = client.put(
        "/api/integrations/agent-llm",
        json=_payload(model_keys={PRO_REF: ""}, models=[PRO_ENTRY]),
    )
    assert cleared.status_code == 200
    assert cleared.json()["model_key_refs"] == []
    secrets = _stored_secrets()
    assert f"model_key:{PRO_REF}" not in secrets
    assert secrets["api_key"] == KEY_DEFAULT


def test_model_keys_for_unknown_refs_are_pruned(client: TestClient) -> None:
    response = client.put(
        "/api/integrations/agent-llm",
        json=_payload(KEY_DEFAULT, model_keys={"ghost/model": KEY_GHOST}, models=[PRO_ENTRY]),
    )
    assert response.status_code == 200
    assert response.json()["model_key_refs"] == []
    assert "model_key:ghost/model" not in _stored_secrets()


def test_secret_requires_at_least_one_field(client: TestClient) -> None:
    empty = client.put("/api/integrations/agent-llm", json={"public_config": {}, "secret": {}})
    assert empty.status_code == 422

    bad_ref = client.put(
        "/api/integrations/agent-llm",
        json={"public_config": {}, "secret": {"model_keys": {"no-slash": KEY_GHOST}}},
    )
    assert bad_ref.status_code == 422


def test_set_default_swaps_config_and_keys(client: TestClient) -> None:
    client.put(
        "/api/integrations/agent-llm",
        json=_payload(
            KEY_DEFAULT,
            model_keys={PRO_REF: KEY_PRO},
            models=[{**PRO_ENTRY, "base_url": BASE_URL}],
        ),
    )

    response = client.post("/api/integrations/agent-llm/default-model", json={"ref": PRO_REF})

    assert response.status_code == 200
    body = response.json()
    assert body["public_config"]["provider"] == "deepseek-official"
    assert body["public_config"]["model"] == "deepseek-v4-pro"
    assert body["public_config"]["base_url"] == BASE_URL
    assert body["public_config"]["models"] == [
        {"provider": "deepseek-official", "model": "deepseek-v4-flash", "enabled": True}
    ]
    # hint 跟随新默认 key（末 4 位 cdef）；旧默认 key 沉淀为旧默认条目的独立 key
    assert body["secret_hint"] == "已配置 · ****cdef"
    secrets = _stored_secrets()
    assert secrets["api_key"] == KEY_PRO
    assert secrets[f"model_key:{DEFAULT_REF}"] == KEY_DEFAULT
    assert f"model_key:{PRO_REF}" not in secrets
    assert KEY_PRO not in response.text
    assert KEY_DEFAULT not in response.text


def test_set_default_without_override_key_keeps_shared_key(client: TestClient) -> None:
    _put_with_models(client, KEY_DEFAULT, [PRO_ENTRY])

    response = client.post("/api/integrations/agent-llm/default-model", json={"ref": PRO_REF})

    assert response.status_code == 200
    secrets = _stored_secrets()
    assert secrets["api_key"] == KEY_DEFAULT
    assert f"model_key:{DEFAULT_REF}" not in secrets


def test_set_default_idempotent_and_error_paths(client: TestClient) -> None:
    _put_with_models(client, KEY_DEFAULT, [PRO_ENTRY, QWEN_ENTRY])

    already_default = client.post("/api/integrations/agent-llm/default-model", json={"ref": DEFAULT_REF})
    assert already_default.status_code == 200
    assert already_default.json()["public_config"]["model"] == "deepseek-v4-flash"
    assert already_default.json()["public_config"]["models"][0]["model"] == "deepseek-v4-pro"

    unknown = client.post("/api/integrations/agent-llm/default-model", json={"ref": "ghost/model"})
    assert unknown.status_code == 404
    assert unknown.json()["code"] == "AGENT_MODEL_NOT_FOUND"

    disabled = client.post("/api/integrations/agent-llm/default-model", json={"ref": QWEN_REF})
    assert disabled.status_code == 409
    assert disabled.json()["code"] == "AGENT_MODEL_DISABLED"


def test_set_default_requires_integration_row(client: TestClient) -> None:
    response = client.post("/api/integrations/agent-llm/default-model", json={"ref": PRO_REF})
    assert response.status_code == 404
    assert response.json()["code"] == "INTEGRATION_NOT_FOUND"

    invalid_ref = client.post("/api/integrations/agent-llm/default-model", json={"ref": "noslash"})
    assert invalid_ref.status_code == 422


def test_model_scoped_connection_test(client: TestClient) -> None:
    _put_with_models(client, KEY_DEFAULT, [{**PRO_ENTRY, "base_url": BASE_URL}])

    with respx.mock(assert_all_called=True) as router:
        router.get(BASE_URL).mock(return_value=httpx.Response(401))
        scoped = client.post("/api/integrations/agent-llm/test", json={"model_ref": PRO_REF})
    assert scoped.status_code == 200
    result = scoped.json()
    assert result["ref"] == PRO_REF
    assert result["success"] is True
    assert result["latency_ms"] is not None
    assert result["tested_at"] is not None
    assert KEY_DEFAULT not in scoped.text
    # 附加模型测试不动行状态
    row = client.get("/api/integrations/agent-llm").json()
    assert row["connection_status"] == "未测试"

    # 默认模型测试落行状态（与旧语义一致）
    defaulted = client.post("/api/integrations/agent-llm/test", json={"model_ref": DEFAULT_REF})
    assert defaulted.status_code == 200
    assert defaulted.json()["ref"] == DEFAULT_REF
    row = client.get("/api/integrations/agent-llm").json()
    assert row["connection_status"] == "连接正常"
    assert row["last_tested_at"] is not None


def test_model_scoped_connection_test_error_paths(client: TestClient) -> None:
    _put_with_models(client, KEY_DEFAULT, [PRO_ENTRY])

    unknown = client.post("/api/integrations/agent-llm/test", json={"model_ref": "ghost/model"})
    assert unknown.status_code == 404
    assert unknown.json()["code"] == "AGENT_MODEL_NOT_FOUND"

    other_provider = client.post("/api/integrations/embedding/test", json={"model_ref": PRO_REF})
    assert other_provider.status_code == 422
    assert other_provider.json()["code"] == "MODEL_REF_UNSUPPORTED"

    invalid_body = client.post("/api/integrations/agent-llm/test", content="not-json")
    assert invalid_body.status_code == 422


def test_disabled_model_can_still_be_tested(client: TestClient) -> None:
    _put_with_models(client, KEY_DEFAULT, [QWEN_ENTRY])

    with respx.mock(assert_all_called=True) as router:
        router.get(SILICONFLOW_URL).mock(return_value=httpx.Response(200))
        response = client.post("/api/integrations/agent-llm/test", json={"model_ref": QWEN_REF})
    assert response.status_code == 200
    assert response.json()["success"] is True


def test_delete_in_use_model_rejected(client: TestClient) -> None:
    _put_with_models(client, KEY_DEFAULT, [PRO_ENTRY, {**QWEN_ENTRY, "enabled": True}])
    app = client.app
    app.state.feishu_bot_supervisor = _StubSupervisor(frozenset({PRO_REF}))  # type: ignore[union-attr]

    blocked = client.put("/api/integrations/agent-llm", json=_payload(models=[QWEN_ENTRY]))
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "AGENT_MODEL_IN_USE"
    assert PRO_REF in blocked.json()["message"]

    # 保留 PRO、移除未引用的 QWEN：放行
    kept = client.put("/api/integrations/agent-llm", json=_payload(models=[PRO_ENTRY]))
    assert kept.status_code == 200
    assert kept.json()["public_config"]["models"] == [
        {"provider": "deepseek-official", "model": "deepseek-v4-pro", "enabled": True}
    ]
