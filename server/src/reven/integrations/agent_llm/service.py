"""Agent LLM 集成的连接测试：校验密钥已配置，配置了 base_url 时做一次轻量可达性检查。

不做真实 LLM 推理调用；任何 HTTP 响应（含 4xx）都说明端点网络/TLS 可达。
"""

import time

import httpx

from reven.integrations.service import ConnectionTestResult, register_connection_test_adapter


async def test_agent_llm_connection(
    public_config: dict[str, object],
    secrets: dict[str, str] | None,
) -> ConnectionTestResult:
    api_key = secrets.get("api_key") if secrets else None
    if not api_key:
        return ConnectionTestResult(False, "Agent LLM API Key 尚未配置")
    base_url = public_config.get("base_url")
    if not isinstance(base_url, str) or not base_url:
        # 未覆盖 base_url 时使用 provider 默认端点，仅确认密钥已配置
        return ConnectionTestResult(True)
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=10, trust_env=False) as http:
            await http.get(base_url)
    except Exception as exc:
        return ConnectionTestResult(False, f"Agent LLM 端点不可达（{type(exc).__name__}）")
    return ConnectionTestResult(True, latency_ms=int((time.monotonic() - started) * 1000))


def register_agent_llm_adapter() -> None:
    register_connection_test_adapter("agent-llm", test_agent_llm_connection)
