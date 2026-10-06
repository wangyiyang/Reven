"""只恢复原 checkpoint，不重发消息或重复业务副作用。"""

import asyncio

import pytest
from agent_service_support import DEFAULT_REF, ServiceRig
from langchain_core.messages import HumanMessage
from reven.agent.context import ADMIN_ACTOR, AgentContext
from reven.agent.errors import AgentRuntimeError
from reven.agent.executor import ToolExecutor
from reven.agent.models import AgentRun
from reven.agent.persistence_types import AgentSessionBusyError, RunStatus
from reven.agent.tool_definition import ToolDefinition
from reven.crm.models import Customer
from sqlalchemy import func, select


@pytest.mark.anyio
async def test_commit_checkpoint_gap_rebuild_restores_one_operation_and_one_input(
    rig: ServiceRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = ToolExecutor.execute
    interrupted = False

    async def gap(
        executor: ToolExecutor, definition: ToolDefinition, args: dict[str, object], context: AgentContext, call_id: str
    ) -> object:
        nonlocal interrupted
        result = await original(executor, definition, args, context, call_id)
        if definition.name == "crm_customer_create" and not interrupted:
            interrupted = True
            raise RuntimeError("commit 后 checkpoint 前注入中断")
        return result

    monkeypatch.setattr(ToolExecutor, "execute", gap)
    rig.tool_calls["新客户"] = [{"name": "crm_customer_create", "id": "create-fixed", "args": {"name": "客户甲"}}]
    service, runtime = await rig.build()
    turn = await service.chat("新客户", "sid")
    assert turn.run_id is not None
    saved = await service.get_run(turn.run_id)
    assert saved.status == "interrupted" and len(saved.operations) == 1
    raw = await service.store.raw_run(turn.run_id, ADMIN_ACTOR)
    original_session_uuid = raw.session_id
    with pytest.raises(AgentSessionBusyError):
        await service.chat("不能抢跑新一轮", "sid")
    await service.close()
    await runtime.close()
    restored, new_runtime = await rig.build()
    finished = await restored.resume_run(turn.run_id, session_id="sid")
    assert finished.run_id == turn.run_id and finished.session_id == "sid"
    state = await restored.get_run(turn.run_id)
    assert state.status == "completed" and len(state.operations) == 1
    run = await restored.store.raw_run(turn.run_id, ADMIN_ACTOR)
    assert run.session_id == original_session_uuid
    graph, _ = await restored.execution.prepare(run)
    checkpoint = await new_runtime.state(graph, run)
    assert len([message for message in checkpoint.values["messages"] if isinstance(message, HumanMessage)]) == 1
    async with rig.factory() as db:
        assert await db.scalar(select(func.count()).select_from(Customer)) == 1


@pytest.mark.anyio
async def test_execution_deadline_keeps_original_busy_run_and_explicit_none_resume(rig: ServiceRig) -> None:
    service, _ = await rig.build(run_timeout_seconds=0.03)
    rig.block_ref = DEFAULT_REF
    turn = await service.chat("模型超过执行期限", "sid")
    assert turn.run_id is not None
    state = await service.get_run(turn.run_id)
    assert state.status == "interrupted" and state.error_code == "AGENT_EXECUTION_TIMEOUT"
    assert not state.operations
    with pytest.raises(AgentSessionBusyError):
        await service.chat("新一轮", "sid")
    rig.release.set()
    recovered = await service.resume_run(turn.run_id)
    assert recovered.response == f"回复@{DEFAULT_REF}"
    assert (await service.get_run(turn.run_id)).status == "completed"
    assert len([message for message in rig.calls[-1][1] if isinstance(message, HumanMessage)]) == 1


@pytest.mark.anyio
async def test_app_shutdown_cancels_execution_and_new_service_resumes_original_input(rig: ServiceRig) -> None:
    service, runtime = await rig.build()
    rig.block_ref = DEFAULT_REF
    request = asyncio.create_task(service.chat("关闭应用", "sid"))
    await asyncio.wait_for(rig.started.wait(), 2)
    await service.close()
    with pytest.raises(asyncio.CancelledError):
        await request
    await runtime.close()
    saved = (await service.history("sid"))[0]
    assert saved.status == "interrupted"
    rig.release.set()
    rebuilt, _ = await rig.build()
    result = await rebuilt.resume_run(saved.id)
    assert result.run_id == saved.id and result.response == f"回复@{DEFAULT_REF}"


@pytest.mark.anyio
async def test_queued_startup_without_safe_checkpoint_needs_reconciliation(rig: ServiceRig) -> None:
    first, runtime = await rig.build()
    config = await rig.credentials.config()
    assert config is not None
    claim = await first.store.claim("尚未提交图", "queued", ADMIN_ACTOR, "queued-key", config, False)
    await first.close()
    await runtime.close()
    restarted, _ = await rig.build()
    assert (await restarted.get_run(claim.run.id)).status == "interrupted"
    with pytest.raises(AgentRuntimeError) as error:
        await restarted.resume_run(claim.run.id)
    assert error.value.code == "AGENT_RECOVERY_UNSAFE"
    assert (await restarted.get_run(claim.run.id)).status == "needs_reconciliation"
    with pytest.raises(AgentSessionBusyError):
        await restarted.chat("不能从头执行", "queued")
    assert not rig.calls


@pytest.mark.anyio
async def test_checkpoint_metadata_mismatch_refuses_resume_without_new_model_call(rig: ServiceRig) -> None:
    service, runtime = await rig.build(run_timeout_seconds=0.03)
    rig.block_ref = DEFAULT_REF
    turn = await service.chat("等待", "sid")
    assert turn.run_id is not None
    async with rig.factory() as db, db.begin():
        run = await db.get(AgentRun, turn.run_id)
        assert run is not None
        run.revision_id = (await service.update_configuration("新的修订", ["crm_customer_list"])).id
        run.snapshot = {**run.snapshot, "tool_names": ["crm_customer_list"]}
    rig.release.set()
    with pytest.raises(AgentRuntimeError) as error:
        await service.resume_run(turn.run_id)
    assert error.value.code == "AGENT_RECOVERY_UNSAFE"
    assert (await service.get_run(turn.run_id)).status == "needs_reconciliation"
    assert len(rig.calls) == 1
    assert runtime.available


@pytest.mark.anyio
async def test_completed_checkpoint_can_repair_interrupted_business_status(rig: ServiceRig) -> None:
    service, _ = await rig.build()
    turn = await service.chat("已完成图", "sid")
    assert turn.run_id is not None
    async with rig.factory() as db, db.begin():
        run = await db.get(AgentRun, turn.run_id)
        assert run is not None
        run.status = RunStatus.INTERRUPTED
        run.result = None
    restored = await service.resume_run(turn.run_id)
    assert restored.response == f"回复@{DEFAULT_REF}" and len(rig.calls) == 1
    assert (await service.get_run(turn.run_id)).status == "completed"


@pytest.mark.anyio
async def test_resume_interface_budget_returns_original_id_without_cancelling_model(rig: ServiceRig) -> None:
    service, _ = await rig.build()
    rig.errors[DEFAULT_REF] = RuntimeError("初次模型中断")
    original = await service.chat("原消息", "sid")
    assert original.run_id is not None
    assert (await service.get_run(original.run_id)).status == "interrupted"
    rig.errors.clear()
    rig.block_ref = DEFAULT_REF
    service._wait_timeout = 2
    response = await service.resume_run(original.run_id, wait_timeout_seconds=0.005)
    assert response.run_id == original.run_id and "运行仍在继续" in response.response
    await asyncio.wait_for(rig.started.wait(), 2)
    assert original.run_id in service.execution.tasks
    rig.release.set()
    await service.execution.wait(original.run_id, 2)
    assert (await service.get_run(original.run_id)).status == "completed"
