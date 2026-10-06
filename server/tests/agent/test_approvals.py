"""真实业务删除通过持久 HITL，外部命令不修改原参数。"""

import asyncio
from dataclasses import replace
from uuid import UUID

import pytest
from agent_service_support import DEFAULT_ENTRY, ServiceRig
from reven.agent.context import ADMIN_ACTOR, AgentActor
from reven.agent.errors import AgentRuntimeError
from reven.agent.persistence_types import AgentApprovalConflictError, AgentApprovalNotFoundError
from reven.crm.models import Customer


async def _customer(rig: ServiceRig, name: str) -> UUID:
    async with rig.factory() as db, db.begin():
        row = Customer(name=name)
        db.add(row)
        await db.flush()
        return row.id


def _delete_call(entity_id: UUID, name: str, call_id: str) -> dict[str, object]:
    return {
        "name": "crm_customer_delete",
        "id": call_id,
        "args": {"customer_id": str(entity_id), "confirm_customer_name": name},
    }


async def _exists(rig: ServiceRig, entity_id: UUID) -> bool:
    async with rig.factory() as db:
        return await db.get(Customer, entity_id) is not None


@pytest.mark.anyio
async def test_pause_and_approval_survive_rebuild_ordered_reject_and_approve(rig: ServiceRig) -> None:
    first_id, second_id = await _customer(rig, "客户甲"), await _customer(rig, "客户乙")
    rig.tool_calls["删除两个客户"] = [
        _delete_call(first_id, "客户甲", "first"),
        _delete_call(second_id, "客户乙", "second"),
    ]
    service, runtime = await rig.build()
    turn = await service.chat("删除两个客户", "sid")
    assert turn.run_id is not None and "确认 " in turn.response
    waiting = await service.get_run(turn.run_id)
    assert waiting.status == "waiting_approval" and not waiting.operations
    assert [row.tool_call_id for row in waiting.approvals] == ["first", "second"]
    assert await _exists(rig, first_id) and await _exists(rig, second_id)
    await service.close()
    await runtime.close()
    rebuilt, _ = await rig.build()
    partially = await rebuilt.resolve_approval(waiting.approvals[1].id, "approve", "sid")
    assert partially.status == "waiting_approval" and not partially.operations
    finished = await rebuilt.resolve_approval(waiting.approvals[0].id, "reject", "sid")
    assert finished.status == "completed"
    assert [row.tool_call_id for row in finished.operations] == ["second"]
    assert [row.status for row in finished.approvals] == ["rejected", "consumed"]
    assert await _exists(rig, first_id) and not await _exists(rig, second_id)
    duplicate = await rebuilt.resolve_approval(waiting.approvals[1].id, "approve", "sid")
    assert duplicate == finished
    with pytest.raises(AgentApprovalConflictError):
        await rebuilt.resolve_approval(waiting.approvals[0].id, "approve", "sid")
    assert len(rig.calls) == 2


@pytest.mark.anyio
async def test_approval_requires_original_owner_and_external_session(rig: ServiceRig) -> None:
    entity_id = await _customer(rig, "客户甲")
    rig.tool_calls["删除"] = [_delete_call(entity_id, "客户甲", "delete")]
    service, _ = await rig.build()
    turn = await service.chat("删除", "sid")
    assert turn.run_id is not None
    approval = (await service.get_run(turn.run_id)).approvals[0]
    with pytest.raises(AgentApprovalNotFoundError):
        await service.resolve_approval(approval.id, "approve", "other-session")
    with pytest.raises(AgentApprovalNotFoundError):
        await service.resolve_approval(approval.id, "approve", "unknown", actor=AgentActor("other"))
    assert await _exists(rig, entity_id)


@pytest.mark.anyio
async def test_target_drift_refuses_approve_but_allows_reject_without_mutation(rig: ServiceRig) -> None:
    entity_id = await _customer(rig, "客户甲")
    rig.tool_calls["删除"] = [_delete_call(entity_id, "客户甲", "delete")]
    service, _ = await rig.build()
    turn = await service.chat("删除", "sid")
    assert turn.run_id is not None
    approval = (await service.get_run(turn.run_id)).approvals[0]
    async with rig.factory() as db, db.begin():
        customer = await db.get(Customer, entity_id)
        assert customer is not None
        customer.notes = "批准前目标发生变化"
    with pytest.raises(AgentApprovalConflictError):
        await service.resolve_approval(approval.id, "approve", "sid")
    still_waiting = await service.get_run(turn.run_id)
    assert still_waiting.status == "waiting_approval" and still_waiting.approvals[0].status == "pending"
    rejected = await service.resolve_approval(approval.id, "reject", "sid")
    assert rejected.status == "completed" and not rejected.operations
    assert await _exists(rig, entity_id)


@pytest.mark.anyio
async def test_args_tampering_does_not_approve_or_delete(rig: ServiceRig) -> None:
    from reven.agent.models import AgentApproval

    entity_id = await _customer(rig, "客户甲")
    rig.tool_calls["删除"] = [_delete_call(entity_id, "客户甲", "delete")]
    service, _ = await rig.build()
    turn = await service.chat("删除", "sid")
    assert turn.run_id is not None
    approval = (await service.get_run(turn.run_id)).approvals[0]
    async with rig.factory() as db, db.begin():
        row = await db.get(AgentApproval, approval.id)
        assert row is not None
        row.args = {**row.args, "confirm_customer_name": "已篡改"}
    with pytest.raises(AgentApprovalConflictError):
        await service.resolve_approval(approval.id, "approve", "sid")
    assert await _exists(rig, entity_id)


@pytest.mark.anyio
@pytest.mark.parametrize("change", ["endpoint", "tool"])
async def test_resume_requires_frozen_endpoint_and_current_tool_permission(rig: ServiceRig, change: str) -> None:
    entity_id = await _customer(rig, "客户甲")
    rig.tool_calls["删除"] = [_delete_call(entity_id, "客户甲", "delete")]
    service, _ = await rig.build()
    turn = await service.chat("删除", "sid")
    assert turn.run_id is not None
    approval = (await service.get_run(turn.run_id)).approvals[0]
    if change == "endpoint":
        rig.credentials.entries = (replace(DEFAULT_ENTRY, base_url="https://changed.example.com"),)
        expected = "AGENT_CONFIG_CHANGED"
    else:
        await service.update_configuration("仍允许查询", ["crm_customer_list"])
        expected = "AGENT_TOOL_DISABLED"
    with pytest.raises(AgentRuntimeError) as error:
        await service.resolve_approval(approval.id, "approve", "sid")
    assert error.value.code == expected
    state = await service.get_run(turn.run_id)
    assert state.status == "waiting_approval" and state.approvals[0].status == "pending"
    assert await _exists(rig, entity_id)


@pytest.mark.anyio
async def test_concurrent_duplicate_approve_executes_one_delete(rig: ServiceRig) -> None:
    entity_id = await _customer(rig, "客户甲")
    rig.tool_calls["删除"] = [_delete_call(entity_id, "客户甲", "delete")]
    service, _ = await rig.build()
    turn = await service.chat("删除", "sid")
    assert turn.run_id is not None
    approval = (await service.get_run(turn.run_id)).approvals[0]
    first, second = await asyncio.gather(
        service.resolve_approval(approval.id, "approve", "sid"), service.resolve_approval(approval.id, "approve", "sid")
    )
    assert first.status == second.status == "completed"
    assert len(first.operations) == len(second.operations) == 1
    assert not await _exists(rig, entity_id)
    assert (await service.store.raw_run(turn.run_id, ADMIN_ACTOR)).status == "completed"


@pytest.mark.anyio
async def test_approval_interface_budget_keeps_running_id_after_business_commit(rig: ServiceRig) -> None:
    entity_id = await _customer(rig, "客户甲")
    rig.tool_calls["删除"] = [_delete_call(entity_id, "客户甲", "delete")]
    service, _ = await rig.build()
    turn = await service.chat("删除", "sid")
    assert turn.run_id is not None
    approval = (await service.get_run(turn.run_id)).approvals[0]
    service._wait_timeout = 2
    rig.block_ref = "deepseek-official/deepseek-v4-flash"
    response = await service.resolve_approval(approval.id, "approve", "sid", wait_timeout_seconds=0.005)
    assert response.id == turn.run_id and response.status == "running"
    await asyncio.wait_for(rig.started.wait(), 2)
    assert not await _exists(rig, entity_id)
    assert turn.run_id in service.execution.tasks
    rig.release.set()
    await service.execution.wait(turn.run_id, 2)
    assert (await service.get_run(turn.run_id)).status == "completed"
