"""POST /api/agent/chat 路由测试：鉴权、降级映射、参数校验、正常会话。"""

import asyncio
from pathlib import Path

import pytest
from agent_service_support import EXTRA_REF, ServiceRig
from fastapi.testclient import TestClient
from reven.agent import AgentConfig, AgentRuntime
from reven.agent.errors import AgentRuntimeError
from reven.agent.mcp_server import AgentMcpContext
from reven.agent.service import AgentService


class _StubRuntime:
    """AgentService 内部 runtime 替身，绕开真实 dsh 子进程。"""

    default_model_ref = "test/model"

    def __init__(self, *, error: Exception | None = None, reply: tuple[str, str] = ("sess-fixed", "回声")) -> None:
        self.error = error
        self.reply = reply
        self.calls: list[tuple[str, str | None]] = []

    async def chat(self, message: str, session_id: str | None = None, *, model: str | None = None) -> tuple[str, str]:
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
    client.app.state.agent_service = AgentService(_failed_runtime(tmp_path, monkeypatch))

    response = client.post("/api/agent/chat", json={"message": "你好"})

    assert response.status_code == 502
    assert response.json()["code"] == "AGENT_RUNTIME_UNAVAILABLE"


def test_chat_returns_502_on_runtime_error(workbench: tuple[TestClient, object]) -> None:
    client, _ = workbench
    client.app.state.agent_service = AgentService(
        _StubRuntime(error=AgentRuntimeError("AGENT_CHAT_FAILED", "dsh 会话执行失败"))
    )

    response = client.post("/api/agent/chat", json={"message": "你好"})

    assert response.status_code == 502
    assert response.json()["code"] == "AGENT_CHAT_FAILED"


def test_chat_error_response_carries_only_stable_code_and_session_id(workbench: tuple[TestClient, object]) -> None:
    """#176 P1：chat 错误响应只含稳定 code 与脱敏 message（code+session_id），无 dsh 异常原文。"""
    client, _ = workbench
    client.app.state.agent_service = AgentService(
        _StubRuntime(error=AgentRuntimeError("AGENT_CHAT_FAILED", "dsh 会话执行失败（session_id=sess-abc）"))
    )

    response = client.post("/api/agent/chat", json={"message": "你好", "session_id": "sess-abc"})

    assert response.status_code == 502
    assert response.json() == {"code": "AGENT_CHAT_FAILED", "message": "dsh 会话执行失败（session_id=sess-abc）"}


def test_chat_success_and_session_id_passthrough(workbench: tuple[TestClient, object]) -> None:
    client, _ = workbench
    stub = _StubRuntime()
    client.app.state.agent_service = AgentService(stub)

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


def test_chat_uses_shared_external_session_choice_without_changing_json(workbench, tmp_path, monkeypatch) -> None:
    client, _ = workbench
    rig = ServiceRig(tmp_path, monkeypatch)
    service, runtime = client.portal.call(rig.build)
    client.app.state.agent_service = service
    session_id = "feishu:oc_shared:ou_boss"
    try:
        client.portal.call(service.use_model, session_id, EXTRA_REF)
        response = client.post("/api/agent/chat", json={"message": "跨入口继续", "session_id": session_id})
        assert response.status_code == 200
        assert response.json() == {"session_id": session_id, "response": f"回复@{EXTRA_REF}"}
        assert rig.instances[0].calls == []
        assert rig.instances[1].calls == [("跨入口继续", session_id)]
    finally:
        client.portal.call(runtime.close)
