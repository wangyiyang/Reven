"""Embedding 连接测试 adapter 与 factory 辅助函数的测试。"""

import httpx
import pytest
import respx
from reven.integrations.embedding.service import test_embedding_connection as embedding_connection_adapter
from reven.rss.embedding import BGE_M3_MODEL


def _embedding_body(model: str = BGE_M3_MODEL) -> dict[str, object]:
    return {"object": "list", "model": model, "data": [{"object": "embedding", "index": 0, "embedding": [0.5] * 1024}]}


@pytest.mark.anyio
async def test_adapter_reports_missing_api_key() -> None:
    result = await embedding_connection_adapter({"base_url": "https://api.siliconflow.cn"}, None)

    assert result.success is False
    assert result.message == "Embedding API Key 尚未配置"


@pytest.mark.anyio
@respx.mock
async def test_adapter_returns_latency_on_success() -> None:
    route = respx.post("https://embedding.example.com/v1/embeddings").mock(
        return_value=httpx.Response(200, json=_embedding_body())
    )

    result = await embedding_connection_adapter(
        {"base_url": "https://embedding.example.com", "model": BGE_M3_MODEL},
        {"api_key": "sk-test"},
    )

    assert result.success is True
    assert result.latency_ms is not None and result.latency_ms >= 0
    assert route.calls[0].request.headers["authorization"] == "Bearer sk-test"


@pytest.mark.anyio
@respx.mock
async def test_adapter_surfaces_error_code_without_leaking_key() -> None:
    # HTTP 400 不可重试，连接测试立即失败
    respx.post("https://api.siliconflow.cn/v1/embeddings").mock(return_value=httpx.Response(400))

    result = await embedding_connection_adapter({}, {"api_key": "sk-top-secret"})

    assert result.success is False
    assert result.message == "Embedding 连接失败（EMBEDDING_HTTP_ERROR）"
    assert "sk-top-secret" not in (result.message or "")


@pytest.mark.anyio
@respx.mock
async def test_adapter_rejects_mismatched_model_response() -> None:
    respx.post("https://api.siliconflow.cn/v1/embeddings").mock(
        return_value=httpx.Response(200, json=_embedding_body(model="other/model"))
    )

    result = await embedding_connection_adapter({}, {"api_key": "sk-test"})

    assert result.success is False
    assert result.message == "Embedding 连接失败（EMBEDDING_MODEL_MISMATCH）"
