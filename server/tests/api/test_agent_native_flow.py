"""真实服务、图和 PostgreSQL 经过 REST 的审批/去重/配置流程；模型不触网。"""

from functools import partial

import pytest
from agent_service_support import ServiceRig
from reven.agent.context import AgentActor
from reven.agent.models import AgentRun, AgentSession
from sqlalchemy import func, select


@pytest.fixture
def native_agent(workbench):
    client, factory = workbench
    rig = ServiceRig(factory)
    service, _ = client.portal.call(rig.build)
    client.app.state.agent_service = service
    try:
        yield client, service, rig
    finally:
        client.portal.call(rig.close)


def test_rest_whitespace_input_is_rejected_before_session_or_run_creation(native_agent) -> None:
    client, service, rig = native_agent
    response = client.post("/api/agent/chat", json={"message": " \t\n"})
    assert response.status_code == 422 and response.json()["code"] == "AGENT_INPUT_INVALID"
    assert "X-Agent-Run-ID" not in response.headers
    assert not rig.calls and not service.execution.tasks

    async def persisted_counts() -> tuple[int, int]:
        async with rig.factory() as session:
            session_count = await session.scalar(select(func.count()).select_from(AgentSession))
            run_count = await session.scalar(select(func.count()).select_from(AgentRun))
            return session_count, run_count

    assert client.portal.call(persisted_counts) == (0, 0)


def test_rest_anonymous_retry_attaches_original_run_and_history(native_agent) -> None:
    client, _, rig = native_agent
    payload, headers = {"message": "首次提问"}, {"Idempotency-Key": "first-message"}
    first = client.post("/api/agent/chat", json=payload, headers=headers)
    repeated = client.post("/api/agent/chat", json=payload, headers=headers)
    assert first.status_code == repeated.status_code == 200
    assert first.json() == repeated.json()
    assert first.headers["X-Agent-Run-ID"] == repeated.headers["X-Agent-Run-ID"]
    assert set(first.json()) == {"session_id", "response"} and len(rig.calls) == 1
    history = client.get("/api/agent/history", params={"session_id": first.json()["session_id"]})
    assert history.status_code == 200 and len(history.json()) == 1
    assert history.json()[0]["message"] == "首次提问" and history.json()[0]["status"] == "completed"
    conflict = client.post("/api/agent/chat", json={"message": "不同输入"}, headers=headers)
    assert conflict.status_code == 409 and conflict.json()["code"] == "AGENT_REQUEST_CONFLICT"
    assert len(rig.calls) == 1


def test_rest_configuration_versions_are_immutable_and_new_turn_uses_new_prompt(native_agent) -> None:
    client, _, rig = native_agent
    original = client.get("/api/agent/config").json()
    updated = client.put("/api/agent/config", json={"prompt": "新的经营助手指令", "tool_names": ["crm_customer_list"]})
    assert updated.status_code == 200
    assert updated.json()["id"] != original["id"] and updated.json()["version"] > original["version"]
    assert client.get(f"/api/agent/config/revisions/{original['id']}").json() == original
    turn = client.post("/api/agent/chat", json={"message": "新指令的会话", "session_id": "config-session"})
    assert turn.status_code == 200 and rig.calls[-1][1][0].content == "新的经营助手指令"
    assert client.get(f"/api/agent/runs/{turn.headers['X-Agent-Run-ID']}").json()["message"] == "新指令的会话"


def test_rest_unknown_tool_is_rejected_without_creating_revision(native_agent) -> None:
    client, _, _ = native_agent
    original = client.get("/api/agent/config").json()
    response = client.put("/api/agent/config", json={"prompt": "无效的工具配置", "tool_names": ["shell_execute"]})
    assert response.status_code == 422 and response.json()["code"] == "AGENT_TOOL_UNKNOWN"
    assert client.get("/api/agent/config").json() == original


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_rest_confirmation_checks_original_session_and_repeat_decision(native_agent, decision: str) -> None:
    client, _, rig = native_agent
    created = client.post("/api/crm/customers", json={"name": "待确认客户"})
    assert created.status_code == 201
    customer_id = created.json()["id"]
    rig.tool_calls["删除待确认客户"] = [
        {
            "name": "crm_customer_delete",
            "args": {"customer_id": customer_id, "confirm_customer_name": "待确认客户"},
            "id": "rest-delete",
            "type": "tool_call",
        }
    ]
    turn = client.post("/api/agent/chat", json={"message": "删除待确认客户", "session_id": "approval-session"})
    assert turn.status_code == 200
    path = f"/api/agent/runs/{turn.headers['X-Agent-Run-ID']}"
    run = client.get(path).json()
    assert run["status"] == "waiting_approval" and len(run["approvals"]) == 1
    approval_path = f"/api/agent/approvals/{run['approvals'][0]['id']}/resolve"
    wrong = client.post(approval_path, json={"decision": decision, "session_id": "other-session"})
    assert wrong.status_code == 404
    assert client.get(f"/api/crm/customers/{customer_id}").status_code == 200
    accepted = client.post(approval_path, json={"decision": decision, "session_id": "approval-session"})
    assert accepted.status_code == 200 and accepted.json()["status"] == "completed"
    repeated = client.post(approval_path, json={"decision": decision, "session_id": "approval-session"})
    assert repeated.status_code == 200
    opposite = "reject" if decision == "approve" else "approve"
    assert client.post(approval_path, json={"decision": opposite, "session_id": "approval-session"}).status_code == 409
    final = client.get(path).json()
    assert len(final["operations"]) == (1 if decision == "approve" else 0)
    assert final["approvals"][0]["status"] == ("consumed" if decision == "approve" else "rejected")
    assert client.get(f"/api/crm/customers/{customer_id}").status_code == (404 if decision == "approve" else 200)


def test_rest_admin_cannot_read_or_reuse_feishu_owned_run(native_agent) -> None:
    client, service, _ = native_agent
    actor, session_id = AgentActor("feishu:ou_boss", "feishu"), "feishu:oc_1:ou_boss"
    turn = client.portal.call(partial(service.chat, "飞书原用户的会话", session_id, actor=actor))
    assert client.get(f"/api/agent/runs/{turn.run_id}").status_code == 404
    assert client.get("/api/agent/history", params={"session_id": session_id}).status_code == 403
    response = client.post(
        "/api/agent/chat", json={"message": "企图复用", "session_id": session_id}, headers={"X-User-ID": actor.owner_id}
    )
    assert response.status_code == 403 and response.json()["code"] == "AGENT_SESSION_FORBIDDEN"
