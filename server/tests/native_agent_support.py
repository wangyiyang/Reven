"""原生 Agent 测试的确定性 Chat Completions HTTP 替身。"""

import json
from typing import Any

import httpx


def completion(
    *, content: str = "已完成", reasoning: str = "测试推理", calls: list[dict[str, Any]] | None = None
) -> httpx.Response:
    message: dict[str, Any] = {"role": "assistant", "content": content, "reasoning_content": reasoning}
    if calls:
        message["tool_calls"] = [
            {
                "id": call["id"],
                "type": "function",
                "function": {"name": call["name"], "arguments": json.dumps(call["args"])},
            }
            for call in calls
        ]
    return httpx.Response(
        200,
        json={
            "id": "chat-test",
            "object": "chat.completion",
            "created": 0,
            "model": "deepseek-v4-flash",
            "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if calls else "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        },
    )


class ToolProtocol:
    def __init__(self, calls: list[dict[str, Any]]) -> None:
        self.calls = calls
        self.requests: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        self.requests.append(payload)
        if payload["messages"][-1]["role"] == "user" and len(self.requests) == 1:
            return completion(content="", reasoning="先调用业务工具", calls=self.calls)
        return completion()
