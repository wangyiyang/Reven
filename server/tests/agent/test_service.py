"""持久配置、去重、可信身份与请求等待生命周期。"""

import asyncio
from dataclasses import FrozenInstanceError

import pytest
from agent_service_support import DEFAULT_REF, EXTRA_REF, ServiceRig
from reven.agent.context import AgentActor
from reven.agent.errors import AgentNotConfiguredError
from reven.agent.persistence_types import (
    AgentPersistenceError,
    AgentRequestConflictError,
    AgentRunNotFoundError,
    AgentSessionBusyError,
    AgentSessionOwnershipError,
)


@pytest.mark.anyio
async def test_revision_is_immutable_and_new_run_observes_new_prompt(rig: ServiceRig) -> None:
    service, _ = await rig.build()
    first = await service.get_configuration()
    one = await service.chat("第一轮", "sid")
    second = await service.update_configuration("新的经营助手指令", ["crm_customer_list"])
    two = await service.chat("第二轮", "sid")
    assert second.id != first.id and second.version > first.version
    assert (await service.get_revision(first.id)) == first
    assert rig.calls[0][1][0].content == first.prompt
    assert rig.calls[-1][1][0].content == second.prompt
    assert one.session_id == two.session_id == "sid"
    history = await service.history("sid")
    assert {row.message for row in history} == {"第一轮", "第二轮"}
    assert all(row.status == "completed" for row in history)


@pytest.mark.anyio
async def test_config_rejects_unknown_tools_empty_prompt_and_duplicate_tools(rig: ServiceRig) -> None:
    service, _ = await rig.build()
    with pytest.raises(AgentPersistenceError) as unknown:
        await service.update_configuration("有效指令", ["shell_execute"])
    assert unknown.value.code == "AGENT_TOOL_UNKNOWN"
    with pytest.raises(Exception, match="指令不能为空"):
        await service.update_configuration(" ", [])
    with pytest.raises(Exception, match="工具名称必须唯一"):
        await service.update_configuration("有效指令", ["crm_customer_list", "crm_customer_list"])


@pytest.mark.anyio
async def test_retry_key_without_session_attaches_original_session_and_conflicts_are_explicit(rig: ServiceRig) -> None:
    service, _ = await rig.build()
    first = await service.chat("相同问题", request_key="first-key")
    second = await service.chat("相同问题", request_key="first-key")
    assert first == second and len(first.session_id) == 32
    assert len(rig.calls) == 1
    with pytest.raises(AgentRequestConflictError):
        await service.chat("不同问题", request_key="first-key")
    with pytest.raises(AgentRequestConflictError):
        await service.chat("相同问题", "different-sid", request_key="first-key")
    third = await service.chat("相同问题", first.session_id, request_key="second-key")
    assert third.run_id != first.run_id and len(rig.calls) == 2
    with pytest.raises(FrozenInstanceError):
        first.response = "不能修改"  # type: ignore[misc]


@pytest.mark.anyio
async def test_concurrent_anonymous_key_claims_one_run(rig: ServiceRig) -> None:
    service, _ = await rig.build()
    one, two = await asyncio.gather(
        service.chat("并发重发", request_key="concurrent"), service.chat("并发重发", request_key="concurrent")
    )
    assert one.run_id == two.run_id and one.session_id == two.session_id
    assert len(rig.calls) == 1


@pytest.mark.anyio
async def test_wait_timeout_retains_background_run_busy_session_and_independent_session(rig: ServiceRig) -> None:
    service, _ = await rig.build()
    rig.block_ref = DEFAULT_REF
    first = await service.chat("阻塞模型", "sid", request_key="blocked", wait_timeout_seconds=0.001)
    await asyncio.wait_for(rig.started.wait(), 2)
    assert first.run_id is not None and "运行仍在继续" in first.response
    retry = await service.chat("阻塞模型", "sid", request_key="blocked", wait_timeout_seconds=0.001)
    assert retry.run_id == first.run_id
    with pytest.raises(AgentSessionBusyError) as error:
        await service.chat("新一轮", "sid", request_key="new-key")
    assert error.value.run_id == first.run_id
    await service.use_model("other", EXTRA_REF)
    other = await service.chat("独立会话", "other")
    assert other.response == f"回复@{EXTRA_REF}"
    rig.release.set()
    await service.execution.wait(first.run_id, 2)
    assert (await service.get_run(first.run_id)).status == "completed"
    assert len(rig.calls) == 2


@pytest.mark.anyio
async def test_cancelled_interface_wait_does_not_cancel_owned_execution(rig: ServiceRig) -> None:
    service, _ = await rig.build()
    rig.block_ref = DEFAULT_REF
    request = asyncio.create_task(service.chat("断开请求", "sid"))
    await asyncio.wait_for(rig.started.wait(), 2)
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    run = (await service.history("sid"))[0]
    assert run.status == "running" and run.id in service.execution.tasks
    rig.release.set()
    await service.execution.wait(run.id, 2)
    assert (await service.get_run(run.id)).status == "completed"


@pytest.mark.anyio
async def test_get_unknown_history_does_not_create_session_and_actor_is_scoped(rig: ServiceRig) -> None:
    service, _ = await rig.build()
    assert await service.history("unknown") == ()
    assert await service.store.session("unknown", AgentActor("admin")) is None
    turn = await service.chat("管理员会话", "sid")
    assert turn.run_id is not None
    with pytest.raises(AgentSessionOwnershipError):
        await service.history("sid", actor=AgentActor("someone-else"))
    with pytest.raises(AgentRunNotFoundError):
        await service.get_run(turn.run_id, actor=AgentActor("someone-else"))
    with pytest.raises(AgentRunNotFoundError):
        await service.get_run(turn.run_id, session_id="unknown")


@pytest.mark.anyio
async def test_feishu_owner_and_current_whitelist_control_all_queries(rig: ServiceRig) -> None:
    service, _ = await rig.build()
    actor = AgentActor("feishu:ou_boss", "feishu")
    turn = await service.chat("可信飞书请求", "feishu:chat:ou_boss", actor=actor)
    assert turn.run_id is not None
    with pytest.raises(AgentRunNotFoundError):
        await service.get_run(turn.run_id, actor=AgentActor("feishu:ou_other", "feishu"))
    rig.credentials.whitelist = ()
    with pytest.raises(AgentSessionOwnershipError):
        await service.get_run(turn.run_id, actor=actor)
    with pytest.raises(AgentSessionOwnershipError):
        await service.resume_run(turn.run_id, actor=actor)


@pytest.mark.anyio
async def test_unconfigured_model_is_explicit_and_does_not_claim_run(rig: ServiceRig) -> None:
    rig.credentials.entries = None
    service, _ = await rig.build()
    with pytest.raises(AgentNotConfiguredError):
        await service.chat("未配置", "sid")
    assert not rig.calls and await service.history("sid") == ()
