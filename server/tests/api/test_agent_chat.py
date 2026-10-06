"""对话 API 兼容响应、可信身份、请求编号与稳定错误映射。"""

import pytest
from agent_api_support import RUN_ID, ApiAgentStub
from fastapi.testclient import TestClient
from reven.agent.context import ADMIN_ACTOR
from reven.agent.errors import AgentRuntimeError
from reven.agent.persistence_types import AgentSessionBusyError, AgentSessionOwnershipError


def test_chat_requires_auth(workbench: tuple[TestClient, object]) -> None:
    client, _ = workbench
    client.cookies.clear()
    assert client.post("/api/agent/chat", json={"message": "你好"}).status_code == 401


def test_chat_returns_503_when_not_configured(workbench: tuple[TestClient, object]) -> None:
    client, _ = workbench
    response = client.post("/api/agent/chat", json={"message": "你好"})
    assert response.status_code == 503
    assert response.json()["code"] == "AGENT_NOT_CONFIGURED"


@pytest.mark.parametrize("code", ["AGENT_RUNTIME_UNAVAILABLE", "AGENT_CHAT_FAILED"])
def test_chat_maps_runtime_errors_to_stable_response(workbench, code: str) -> None:
    client, _ = workbench
    client.app.state.agent_service = ApiAgentStub(error=AgentRuntimeError(code, "Agent 暂时无法执行。"))
    response = client.post("/api/agent/chat", json={"message": "你好"})
    assert response.status_code == 502
    assert response.json() == {"code": code, "message": "Agent 暂时无法执行。"}


def test_chat_success_preserves_json_and_forwards_request_identity(workbench) -> None:
    client, _ = workbench
    stub = ApiAgentStub()
    client.app.state.agent_service = stub
    continued = client.post(
        "/api/agent/chat",
        json={"message": "继续聊", "session_id": "sess-abc"},
        headers={"Idempotency-Key": "request-1", "X-User-ID": "feishu:ou_other", "X-Agent-Owner": "other"},
    )
    fresh = client.post("/api/agent/chat", json={"message": "新会话"})
    assert continued.status_code == fresh.status_code == 200
    assert continued.json() == fresh.json() == {"session_id": "sess-fixed", "response": "回声"}
    assert continued.headers["X-Agent-Run-ID"] == str(RUN_ID)
    assert stub.calls == [
        ("chat", "继续聊", "sess-abc", ADMIN_ACTOR, "request-1", None),
        ("chat", "新会话", None, ADMIN_ACTOR, None, None),
    ]


@pytest.mark.parametrize(
    "payload", [{"message": ""}, {"message": "hi", "actor": "other"}, {}, {"message": "hi", "session_id": ""}]
)
def test_chat_validates_payload(workbench, payload: dict[str, object]) -> None:
    client, _ = workbench
    assert client.post("/api/agent/chat", json=payload).status_code == 422


@pytest.mark.parametrize("key", ["", "x" * 257])
def test_chat_validates_request_key(workbench, key: str) -> None:
    client, _ = workbench
    assert client.post("/api/agent/chat", json={"message": "hi"}, headers={"Idempotency-Key": key}).status_code == 422


def test_busy_chat_returns_original_run_number(workbench) -> None:
    client, _ = workbench
    client.app.state.agent_service = ApiAgentStub(error=AgentSessionBusyError(RUN_ID))
    response = client.post("/api/agent/chat", json={"message": "第二轮"})
    assert response.status_code == 409
    assert response.json()["code"] == "AGENT_SESSION_BUSY"
    assert response.headers["X-Agent-Run-ID"] == str(RUN_ID)


def test_rest_cannot_claim_another_channels_session(workbench) -> None:
    client, _ = workbench
    client.app.state.agent_service = ApiAgentStub(error=AgentSessionOwnershipError())
    response = client.post("/api/agent/chat", json={"message": "继续", "session_id": "feishu:chat:ou_other"})
    assert response.status_code == 403
    assert response.json()["code"] == "AGENT_SESSION_FORBIDDEN"
