"""Embedding 集成的连接测试：用配置的服务对测试文本发一次真实 embedding。"""

import time

import httpx

from reven.integrations.service import ConnectionTestResult
from reven.rss.embedding import BGE_M3_MODEL, EmbeddingError, SiliconFlowEmbeddingClient

DEFAULT_EMBEDDING_BASE_URL = "https://api.siliconflow.cn"


async def test_embedding_connection(
    public_config: dict[str, object],
    secrets: dict[str, str] | None,
) -> ConnectionTestResult:
    api_key = secrets.get("api_key") if secrets else None
    if not api_key:
        return ConnectionTestResult(False, "Embedding API Key 尚未配置")
    base_url = public_config.get("base_url")
    model = public_config.get("model")
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(
            base_url=base_url if isinstance(base_url, str) and base_url else DEFAULT_EMBEDDING_BASE_URL,
            timeout=10,
            trust_env=False,
        ) as http:
            client = SiliconFlowEmbeddingClient(
                api_key,
                http=http,
                model=model if isinstance(model, str) and model else BGE_M3_MODEL,
                max_attempts=2,
            )
            outcome = await client.embed(("Reven 连接测试",))
    except EmbeddingError as exc:
        return ConnectionTestResult(False, f"Embedding 连接失败（{exc.code}）")
    except Exception as exc:
        return ConnectionTestResult(False, f"Embedding 连接失败（{type(exc).__name__}）")
    error_code = outcome.error_codes[0]
    if error_code is not None:
        return ConnectionTestResult(False, f"Embedding 连接失败（{error_code}）")
    return ConnectionTestResult(True, latency_ms=int((time.monotonic() - started) * 1000))
