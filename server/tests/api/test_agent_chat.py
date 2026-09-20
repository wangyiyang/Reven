"""POST /api/agent/chat 路由测试：鉴权、降级映射、参数校验、正常会话。"""

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from reven.agent import AgentConfig, AgentRuntime
from reven.agent.errors import AgentRuntimeError
from reven.agent.mcp_server import AgentMcpContext


class _StubRuntime:
    """duck-type 替换 app.state.agent_runtime，绕开真实 dsh 子进程。"""

    def __init__(self, *, error: Exception | None = None, reply: tuple[str, str] = ("sess-fixed", "回声")) -> None:
        self.error = error
        self.reply = reply
        self.calls: list[tuple[str, str | None]] = []

    async def chat(self, message: str, session_id: str | None = None) -> tuple[str, str]:
        if self.error is not None:
            raise self.error
        self.calls.append((message, session_id))
        return self.reply


def _failed_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AgentRuntime:
    def _fail_launch(config: AgentConfig, mcp: AgentMcpContext | None) -> None:
        raise OSError("dsh binary missing")

    monkeypatch.setattr("reven.agent.runtime._launch", _fail_launch)
    runtime = AgentRuntime(
        AgentConfig(
            provider="deepseek-official",
            model="deepseek-v4-flash",
            base_url=None,
            api_key="sk-test",
            dsh_home=tmp_path / "dsh",
            cwd=tmp_path / "dsh",
        )
    )
    asyncio.run(runtime.start())
    return runtime


def test_chat_requires_auth(workbench: tuple[TestClient, object]) -> None:
    client, _ = workbench
    client.cookies.clear()

    response = client.post("/api/agent/chat", json={"message": "你好"})

    assert response.status_code == 401


def test_chat_returns_503_when_not_configured(workbench: tuple[TestClient, object]) -> None:
    client, _ = workbench

    response = client.post("/api/agent/chat", json={"message": "你好"})

    assert response.status_code == 503
    assert response.json()["code"] == "AGENT_NOT_CONFIGURED"


def test_chat_returns_502_when_runtime_start_failed(
    workbench: tuple[TestClient, object], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = workbench
    client.app.state.agent_runtime = _failed_runtime(tmp_path, monkeypatch)

    response = client.post("/api/agent/chat", json={"message": "你好"})

    assert response.status_code == 502
    assert response.json()["code"] == "AGENT_RUNTIME_UNAVAILABLE"


def test_chat_returns_502_on_runtime_error(workbench: tuple[TestClient, object]) -> None:
    client, _ = workbench
    client.app.state.agent_runtime = _StubRuntime(error=AgentRuntimeError("AGENT_CHAT_FAILED", "dsh 会话执行失败"))

    response = client.post("/api/agent/chat", json={"message": "你好"})

    assert response.status_code == 502
    assert response.json()["code"] == "AGENT_CHAT_FAILED"


def test_chat_success_and_session_id_passthrough(workbench: tuple[TestClient, object]) -> None:
    client, _ = workbench
    stub = _StubRuntime()
    client.app.state.agent_runtime = stub

    continued = client.post("/api/agent/chat", json={"message": "继续聊", "session_id": "sess-abc"})
    fresh = client.post("/api/agent/chat", json={"message": "新会话"})

    assert continued.status_code == 200
    assert continued.json() == {"session_id": "sess-fixed", "response": "回声"}
    assert fresh.status_code == 200
    assert stub.calls == [("继续聊", "sess-abc"), ("新会话", None)]


def test_chat_validates_payload(workbench: tuple[TestClient, object]) -> None:
    client, _ = workbench

    assert client.post("/api/agent/chat", json={"message": ""}).status_code == 422
    assert client.post("/api/agent/chat", json={"message": "hi", "unexpected": 1}).status_code == 422
    assert client.post("/api/agent/chat", json={}).status_code == 422
