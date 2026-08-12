import json
from datetime import UTC, datetime

import httpx
import pytest
from reven.rss.ai import SiliconFlowChatClient
from reven.rss.discovery import FeedEntry, PartialLocalizationError
from reven.rss.screening import ScreeningDocument


@pytest.mark.anyio
async def test_chat_client_localizes_entries_as_strict_ordered_json() -> None:
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "items": [
                                        {"index": 0, "title_zh": "智能体系统", "summary_zh": "实践指南"},
                                        {"index": 1, "title_zh": "模型更新", "summary_zh": "版本说明"},
                                    ]
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ],
            },
        )

    async with httpx.AsyncClient(
        base_url="https://api.siliconflow.cn",
        transport=httpx.MockTransport(handler),
    ) as http:
        result = await SiliconFlowChatClient("test-key", model="Qwen/Qwen3-8B", http=http).localize(
            (
                FeedEntry("1", "https://example.com/1", "Agent systems", "Practical guide", datetime.now(UTC)),
                FeedEntry("2", "https://example.com/2", "Model update", "Release notes", None),
            )
        )

    assert [(item.title_zh, item.summary_zh) for item in result] == [
        ("智能体系统", "实践指南"),
        ("模型更新", "版本说明"),
    ]
    assert requests[0]["model"] == "Qwen/Qwen3-8B"
    assert requests[0]["enable_thinking"] is False


@pytest.mark.anyio
async def test_chat_client_localizes_large_inputs_within_provider_batch_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        items = json.loads(payload["messages"][1]["content"])
        if len(items) > 5:
            raise httpx.ReadTimeout("provider batch timeout", request=request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "items": [
                                        {
                                            "index": item["index"],
                                            "title_zh": f"中文 {item['title']}",
                                            "summary_zh": f"中文 {item['summary']}",
                                        }
                                        for item in items
                                    ]
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            },
        )

    entries = tuple(FeedEntry(str(index), None, f"Title {index}", f"Summary {index}", None) for index in range(12))
    async with httpx.AsyncClient(
        base_url="https://api.siliconflow.cn",
        transport=httpx.MockTransport(handler),
    ) as http:
        result = await SiliconFlowChatClient("test-key", model="Qwen/Qwen3-8B", http=http).localize(entries)

    assert [(item.title_zh, item.summary_zh) for item in result] == [
        (f"中文 Title {index}", f"中文 Summary {index}") for index in range(12)
    ]


@pytest.mark.anyio
async def test_chat_client_preserves_successful_batches_when_one_batch_fails() -> None:
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        items = json.loads(json.loads(request.content)["messages"][1]["content"])
        if requests == 2:
            return httpx.Response(500)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "items": [
                                        {
                                            "index": item["index"],
                                            "title_zh": f"中文 {item['title']}",
                                            "summary_zh": f"中文 {item['summary']}",
                                        }
                                        for item in items
                                    ]
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            },
        )

    entries = tuple(FeedEntry(str(index), None, f"Title {index}", f"Summary {index}", None) for index in range(12))
    async with httpx.AsyncClient(
        base_url="https://api.siliconflow.cn",
        transport=httpx.MockTransport(handler),
    ) as http:
        with pytest.raises(PartialLocalizationError) as captured:
            await SiliconFlowChatClient("test-key", model="Qwen/Qwen3-8B", http=http).localize(entries)

    assert requests == 3
    assert captured.value.error_types == ("RuntimeError",)
    assert [(item.title_zh, item.summary_zh) for item in captured.value.localized] == [
        (f"中文 Title {index}", f"中文 Summary {index}")
        if index < 5 or index >= 10
        else (f"Title {index}", f"Summary {index}")
        for index in range(12)
    ]


@pytest.mark.anyio
async def test_chat_client_returns_optional_boundary_judgement() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert b"rules_version" in request.content
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"recommended":true,"score":0.82,"reason":"主题相关"}'}}]},
        )

    async with httpx.AsyncClient(
        base_url="https://api.siliconflow.cn",
        transport=httpx.MockTransport(handler),
    ) as http:
        result = await SiliconFlowChatClient("test-key", model="Qwen/Qwen3-8B", http=http).judge(
            ScreeningDocument(__import__("uuid").uuid4(), "智能体系统", "实践指南"),
            {"rules_version": "rss-v1"},
        )

    assert result.recommended is True
    assert result.score == 0.82
    assert result.reason == "主题相关"


@pytest.mark.anyio
async def test_chat_client_rejects_unstructured_model_output() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "```json\n{}\n```"}}]})

    async with httpx.AsyncClient(
        base_url="https://api.siliconflow.cn",
        transport=httpx.MockTransport(handler),
    ) as http:
        with pytest.raises(RuntimeError, match="响应格式无效"):
            await SiliconFlowChatClient("test-key", model="Qwen/Qwen3-8B", http=http).localize(
                (FeedEntry("1", None, "Agent systems", "Guide", None),)
            )
