"""原生池生命周期与稳定图配置。"""

from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from reven.agent.checkpoint import AgentCheckpoints
from reven.agent.config import AgentConfig
from reven.agent.errors import AgentRuntimeError
from reven.agent.models import AgentRun
from reven.agent.runtime import AgentRuntime, final_response, graph_config
from reven.agent.service import AgentService


def test_final_response_requires_final_ai_without_pending_tool_calls() -> None:
    assert final_response({"messages": [AIMessage(content="最终结果")]}) == "最终结果"
    with pytest.raises(AgentRuntimeError):
        final_response({"messages": [HumanMessage(content="只有输入")]})
    with pytest.raises(AgentRuntimeError):
        final_response({"messages": [AIMessage(content="", tool_calls=[{"id": "call", "name": "tool", "args": {}}])]})


def test_graph_config_has_stable_database_thread_run_and_revision() -> None:
    run = AgentRun(id=uuid4(), session_id=uuid4(), revision_id=uuid4())
    config = graph_config(run)
    assert config["configurable"] == {"thread_id": str(run.session_id)}
    assert config["metadata"] == {"reven_run_id": str(run.id), "reven_revision_id": str(run.revision_id)}


@pytest.mark.anyio
async def test_start_failure_is_degraded_and_redacts_error(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def fail_open(pool: AgentCheckpoints) -> None:
        del pool
        raise OSError("credential=test-leaked-secret")

    monkeypatch.setattr(AgentCheckpoints, "open", fail_open)
    runtime = AgentRuntime(AgentConfig("openai", "gpt-5", None, "test-key"), database_url="postgresql://unused/unused")
    await runtime.start()
    assert runtime.configured and not runtime.available
    assert "test-leaked-secret" not in caplog.text
    await runtime.close()
    await runtime.close()


@pytest.mark.anyio
async def test_unconfigured_service_does_not_need_a_runtime_process() -> None:
    from reven.agent.errors import AgentNotConfiguredError

    runtime = AgentRuntime(None)
    service = AgentService(runtime)
    await service.start()
    with pytest.raises(AgentNotConfiguredError):
        await service.chat("默认未配置")
    await service.close()
    await runtime.close()
