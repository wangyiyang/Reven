import json

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_deepseek import ChatDeepSeek
from native_agent_support import completion
from reven.agent.errors import AgentModelUnavailableError
from reven.agent.providers import RevenChatDeepSeek, build_chat_model


@pytest.mark.anyio
async def test_official_adapter_needs_reasoning_payload_patch() -> None:
    message = AIMessage(content="", additional_kwargs={"reasoning_content": "原始推理"})
    with httpx.Client(trust_env=False) as sync_client:
        async with httpx.AsyncClient(trust_env=False) as async_client:
            upstream = ChatDeepSeek(
                model="deepseek-v4-flash", api_key="test-key", http_client=sync_client, http_async_client=async_client
            )
            adapted = build_chat_model(
                "deepseek-official",
                "deepseek-v4-flash",
                None,
                "test-key",
                http_client=sync_client,
                http_async_client=async_client,
            )
            assert "reasoning_content" not in upstream._get_request_payload([message])["messages"][0]
            assert isinstance(adapted, RevenChatDeepSeek)
            assert adapted._get_request_payload([message])["messages"][0]["reasoning_content"] == "原始推理"


@pytest.mark.anyio
async def test_deepseek_http_roundtrip_preserves_reasoning_and_tool_order() -> None:
    requests: list[dict[str, object]] = []
    calls = [{"id": "call-first", "name": "lookup", "args": {"query": "客户"}}]

    def transport(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.deepseek.com/chat/completions"
        requests.append(json.loads(request.content))
        return completion(calls=calls) if len(requests) == 1 else completion()

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        model = build_chat_model("deepseek-official", "deepseek-v4-flash", None, "test-key", http_async_client=client)
        first = await model.ainvoke([HumanMessage(content="查客户")])
        assert isinstance(first, AIMessage)
        assert first.additional_kwargs["reasoning_content"] == "测试推理"
        second = await model.ainvoke(
            [HumanMessage(content="查客户"), first, ToolMessage(content="甲", tool_call_id="call-first")]
        )
        assert isinstance(second, AIMessage)
        assert second.content == "已完成"
    assert requests[1]["messages"][1]["reasoning_content"] == "测试推理"
    assert requests[1]["messages"][1]["tool_calls"][0]["id"] == "call-first"
    assert requests[1]["messages"][2]["tool_call_id"] == "call-first"
    assert [message["role"] for message in requests[1]["messages"]] == ["user", "assistant", "tool"]


@pytest.mark.anyio
@pytest.mark.parametrize("provider", ["openai", "openai-compatible", "siliconflow"])
async def test_compatible_origins_use_standard_chat_completions(provider: str) -> None:
    def transport(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://compatible.example/v1/chat/completions"
        return completion()

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        model = build_chat_model(
            provider, "standard-model", "https://compatible.example", "test-key", http_async_client=client
        )
        assert (await model.ainvoke("你好")).content == "已完成"


@pytest.mark.parametrize(
    ("provider", "base_url", "api_key"),
    [
        ("anthropic", None, "test-key"),
        ("openai-compatible", None, "test-key"),
        ("openai", "http://unsafe.example", "test-key"),
        ("deepseek-official", None, None),
    ],
)
def test_unavailable_or_unknown_routes_are_explicit_and_secret_free(
    provider: str, base_url: str | None, api_key: str | None
) -> None:
    with pytest.raises(AgentModelUnavailableError) as error:
        build_chat_model(provider, "test-model", base_url, api_key)
    assert error.value.code == "AGENT_MODEL_UNAVAILABLE"
    assert "test-key" not in str(error.value)
