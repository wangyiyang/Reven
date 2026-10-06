"""真实短配置事务和运行创建交错：删除先赢或 claim 先赢均不漏判。"""

import asyncio
from functools import partial
from uuid import UUID

import httpx
import pytest
from agent_service_support import DEFAULT_REF, EXTRA_REF, RigModel, ServiceRig
from reven.agent.config import resolve_agent_config, resolve_agent_model_config
from reven.agent.runtime import AgentRuntime
from reven.agent.service import AgentService
from reven.agent.tool_registry import ToolRegistry
from reven.integrations.service import IntegrationService

INITIAL_MODELS = {
    "public_config": {
        "provider": "deepseek-official",
        "model": "deepseek-v4-flash",
        "models": [{"provider": "openai", "model": "gpt-5", "enabled": True}],
    },
    "secret": {"api_key": "test-model-key"},
}
REMOVE_EXTRA = {"public_config": {"provider": "deepseek-official", "model": "deepseek-v4-flash", "models": []}}
REMOVE_DEFAULT = {"public_config": {"provider": "openai", "model": "gpt-5", "models": []}}


@pytest.fixture
def configured_agent(workbench):
    client, factory = workbench
    assert client.put("/api/integrations/agent-llm", json=INITIAL_MODELS).status_code == 200
    credentials, settings = client.app.state.integration_credentials, client.app.state.settings
    rig = ServiceRig(factory)
    runtime = AgentRuntime(
        None,
        database_url=settings.database_url.get_secret_value(),
        registry=ToolRegistry(factory),
        config_resolver=partial(resolve_agent_config, credentials, settings),
        model_resolver=partial(resolve_agent_model_config, credentials, settings),
        model_factory=lambda config: RigModel(rig=rig, ref=f"{config.provider}/{config.model}"),
    )
    service = AgentService(runtime, credentials, session_factory=factory, wait_timeout_seconds=0.01)
    client.portal.call(service.start)
    client.app.state.agent_service = service
    try:
        yield client, service, rig
    finally:
        client.portal.call(rig.release.set)
        client.portal.call(service.close)
        client.portal.call(runtime.close)


def test_model_delete_commit_wins_before_concurrent_chat_claim(configured_agent, monkeypatch) -> None:
    client, service, rig = configured_agent
    client.portal.call(service.use_model, "race-session", EXTRA_REF)
    original = IntegrationService.upsert_agent_llm

    async def race() -> tuple[httpx.Response, httpx.Response]:
        entered, release = asyncio.Event(), asyncio.Event()

        async def delayed_upsert(self, **kwargs):
            row = await original(self, **kwargs)
            entered.set()
            await release.wait()
            return row

        monkeypatch.setattr(IntegrationService, "upsert_agent_llm", delayed_upsert)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=client.app),
            base_url="https://testserver",
            cookies=dict(client.cookies),
            headers=dict(client.headers),
        ) as http:
            deleting = asyncio.create_task(http.put("/api/integrations/agent-llm", json=REMOVE_EXTRA))
            entered_task = asyncio.create_task(entered.wait())
            done, _ = await asyncio.wait((entered_task, deleting), timeout=2, return_when=asyncio.FIRST_COMPLETED)
            if entered_task not in done:
                entered_task.cancel()
                release.set()
                assert False, deleting.result().text if deleting.done() else "删除事务未进入"
            chatting = asyncio.create_task(
                http.post("/api/agent/chat", json={"message": "删除竞争", "session_id": "race-session"})
            )
            try:
                await asyncio.sleep(0.05)
                assert not chatting.done() and rig.calls == []
            finally:
                release.set()
            deleted, turn = await asyncio.gather(deleting, chatting)
            return deleted, turn

    deleted, turn = client.portal.call(race)
    assert deleted.status_code == 200
    assert turn.status_code == 502 and turn.json()["code"] == "AGENT_MODEL_UNAVAILABLE"
    assert rig.calls == [] and client.portal.call(service.history, "race-session") == ()


@pytest.mark.parametrize(("model_ref", "removal"), [(DEFAULT_REF, REMOVE_DEFAULT), (EXTRA_REF, REMOVE_EXTRA)])
def test_claimed_run_blocks_default_or_extra_model_removal_until_terminal(configured_agent, model_ref, removal) -> None:
    client, service, rig = configured_agent
    if model_ref == EXTRA_REF:
        client.portal.call(service.use_model, "claim-session", EXTRA_REF)
    rig.block_ref = model_ref
    turn = client.post("/api/agent/chat", json={"message": "等待回答", "session_id": "claim-session"})
    assert turn.status_code == 200
    run_id = UUID(turn.headers["X-Agent-Run-ID"])
    client.portal.call(partial(asyncio.wait_for, rig.started.wait(), timeout=2))
    blocked = client.put("/api/integrations/agent-llm", json=removal)
    assert blocked.status_code == 409 and blocked.json()["code"] == "AGENT_MODEL_IN_USE"
    assert model_ref in blocked.json()["message"] and "未完成运行" in blocked.json()["message"]
    assert "切换其他模型" not in blocked.json()["message"]
    client.portal.call(rig.release.set)
    client.portal.call(service.execution.wait, run_id, 2)
    assert client.get(f"/api/agent/runs/{run_id}").json()["status"] == "completed"
    assert client.put("/api/integrations/agent-llm", json=removal).status_code == 200
    assert len(rig.calls) == 1
