"""Agent 管理入口：配置版本、运行历史、显式审批与恢复。"""

import pytest
from agent_api_support import APPROVAL_ID, REVISION_ID, RUN_ID, ApiAgentStub
from reven.agent.context import ADMIN_ACTOR
from reven.agent.errors import AgentError


@pytest.fixture
def managed_agent(workbench):
    client, _ = workbench
    stub = ApiAgentStub()
    client.app.state.agent_service = stub
    return client, stub


def test_configuration_reads_revisions_and_puts_new_prompt(managed_agent) -> None:
    client, stub = managed_agent
    current = client.get("/api/agent/config")
    revision = client.get(f"/api/agent/config/revisions/{REVISION_ID}")
    updated = client.put("/api/agent/config", json={"prompt": "新指令", "tool_names": ["list_customers"]})
    assert current.status_code == revision.status_code == updated.status_code == 200
    assert (
        current.json()
        == revision.json()
        == {
            "id": str(REVISION_ID),
            "version": 2,
            "prompt": "经营助手指令",
            "tool_names": ["list_customers", "delete_customer"],
        }
    )
    assert updated.json()["prompt"] == "新指令"
    assert stub.calls == [
        ("get_configuration",),
        ("get_revision", REVISION_ID),
        ("update_configuration", "新指令", ["list_customers"]),
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {"prompt": "  ", "tool_names": []},
        {"prompt": "指令", "tool_names": ["a", "a"]},
        {"prompt": "指令", "tool_names": [""]},
        {"prompt": "指令", "tool_names": [], "owner_id": "other"},
    ],
)
def test_configuration_validates_content(managed_agent, payload) -> None:
    client, stub = managed_agent
    assert client.put("/api/agent/config", json=payload).status_code == 422
    assert stub.calls == []


def test_run_and_history_expose_request_confirmation_and_committed_results(managed_agent) -> None:
    client, stub = managed_agent
    response = client.get(f"/api/agent/runs/{RUN_ID}", params={"session_id": "rest-session"})
    history = client.get("/api/agent/history", params={"session_id": "rest-session"})
    assert response.status_code == history.status_code == 200
    run = response.json()
    assert history.json() == [run]
    assert run["id"] == str(RUN_ID) and run["message"] == "删除客户甲"
    assert run["status"] == "waiting_approval"
    assert run["approvals"][0]["target_summary"] == "客户甲"
    assert "target_hash" not in run["approvals"][0]
    assert run["operations"][0]["result"] == {"output": "已创建"}
    assert stub.calls == [("get_run", RUN_ID, ADMIN_ACTOR, "rest-session"), ("history", "rest-session", ADMIN_ACTOR)]


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_approval_forwards_original_session_and_server_actor(managed_agent, decision: str) -> None:
    client, stub = managed_agent
    response = client.post(
        f"/api/agent/approvals/{APPROVAL_ID}/resolve", json={"decision": decision, "session_id": "rest-session"}
    )
    assert response.status_code == 200
    assert stub.calls == [("resolve_approval", APPROVAL_ID, decision, "rest-session", ADMIN_ACTOR)]


@pytest.mark.parametrize("body", [None, {"session_id": "rest-session"}])
def test_resume_keeps_legacy_turn_json_and_run_number(managed_agent, body) -> None:
    client, stub = managed_agent
    response = client.post(f"/api/agent/runs/{RUN_ID}/resume", json=body)
    assert response.status_code == 200
    assert response.json() == {"session_id": "sess-fixed", "response": "回声"}
    assert response.headers["X-Agent-Run-ID"] == str(RUN_ID)
    assert stub.calls == [("resume_run", RUN_ID, ADMIN_ACTOR, "rest-session" if body else None)]


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("AGENT_RUN_NOT_FOUND", 404),
        ("AGENT_APPROVAL_NOT_FOUND", 404),
        ("AGENT_SESSION_FORBIDDEN", 403),
        ("AGENT_APPROVAL_CONFLICT", 409),
        ("AGENT_CONFIG_INVALID", 422),
    ],
)
def test_domain_error_mapping_is_explicit(managed_agent, code: str, status: int) -> None:
    client, stub = managed_agent
    stub.error = AgentError(code, "稳定错误消息")
    response = client.get(f"/api/agent/runs/{RUN_ID}")
    assert response.status_code == status
    assert response.json() == {"code": code, "message": "稳定错误消息"}


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("get", "/api/agent/config", None),
        ("put", "/api/agent/config", {"prompt": "指令", "tool_names": []}),
        ("get", f"/api/agent/runs/{RUN_ID}", None),
        ("get", "/api/agent/history?session_id=rest-session", None),
        ("post", f"/api/agent/approvals/{APPROVAL_ID}/resolve", {"decision": "approve", "session_id": "rest-session"}),
        ("post", f"/api/agent/runs/{RUN_ID}/resume", None),
    ],
)
def test_management_routes_require_cookie_auth(managed_agent, method, path, payload) -> None:
    client, stub = managed_agent
    client.cookies.clear()
    kwargs = {} if method == "get" else {"json": payload}
    assert client.request(method, path, **kwargs).status_code == 401
    assert stub.calls == []


def test_approval_requires_session_and_csrf(managed_agent) -> None:
    client, stub = managed_agent
    path = f"/api/agent/approvals/{APPROVAL_ID}/resolve"
    assert client.post(path, json={"decision": "approve"}).status_code == 422
    assert client.post(path, json={"decision": "yes", "session_id": "rest-session"}).status_code == 422
    assert (
        client.post(path, json={"decision": "approve", "session_id": "rest-session", "actor": "other"}).status_code
        == 422
    )
    client.headers.pop("X-Reven-CSRF")
    assert client.post(path, json={"decision": "approve", "session_id": "rest-session"}).status_code == 403
    assert stub.calls == []


def test_lookup_requires_valid_identifiers(managed_agent) -> None:
    client, stub = managed_agent
    assert client.get("/api/agent/runs/not-a-uuid").status_code == 422
    assert client.get("/api/agent/history").status_code == 422
    assert stub.calls == []
