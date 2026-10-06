import asyncio

import pytest
from langchain.agents.middleware.types import ToolCallRequest
from langchain.tools import ToolRuntime
from langchain_core.messages import AIMessage, ToolMessage
from native_transactional_support import followup_args
from reven.agent.persistence_types import ApprovalStatus
from reven.agent.tool_errors import AgentToolDependencyError
from reven.crm.models import Contact, FollowUp
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from tool_execution_support import ToolRig
from tool_execution_support import tool_rig as tool_rig


def _request(rig: ToolRig, calls: list[dict], index: int, responses: tuple[ToolMessage, ...] = ()) -> ToolCallRequest:
    state = {"messages": [AIMessage(content="", tool_calls=calls), *responses]}
    runtime = ToolRuntime(state, rig.context, {}, lambda _: None, calls[index]["id"], None)
    return ToolCallRequest(calls[index], None, state, runtime)


async def _execute(rig: ToolRig, request: ToolCallRequest) -> ToolMessage:
    call = request.tool_call
    output = await rig.execute(call["name"], call["args"], call["id"])
    return ToolMessage(content=str(output), tool_call_id=call["id"])


@pytest.mark.anyio
async def test_later_task_executes_prior_writes_in_original_order_each_with_own_receipt(tool_rig: ToolRig) -> None:
    args = await followup_args(tool_rig)
    calls = [
        {"name": "crm_follow_up_create", "id": f"call-{i}", "args": {**args, "summary": f"顺序{i}"}} for i in range(3)
    ]
    middleware = tool_rig.registry.middleware()

    async def handler(request: ToolCallRequest):
        return await _execute(tool_rig, request)

    results = await asyncio.gather(
        *[middleware.awrap_tool_call(_request(tool_rig, calls, i), handler) for i in (2, 0, 1)]
    )
    assert [item.tool_call_id for item in results] == ["call-2", "call-0", "call-1"]
    async with tool_rig.factory() as session:
        rows = list(await session.scalars(select(FollowUp).order_by(FollowUp.created_at)))
        assert [row.summary for row in rows] == ["顺序0", "顺序1", "顺序2"]


@pytest.mark.anyio
async def test_invalid_prior_write_reports_dependency_and_does_not_claim_later_call_executed(tool_rig: ToolRig) -> None:
    args = await followup_args(tool_rig)
    calls = [
        {"name": "crm_follow_up_create", "id": "invalid-first", "args": {**args, "summary": ""}},
        {"name": "crm_follow_up_create", "id": "unexecuted-second", "args": args},
    ]
    handler_called = False

    async def handler(request: ToolCallRequest):
        nonlocal handler_called
        handler_called = True
        return await _execute(tool_rig, request)

    with pytest.raises(AgentToolDependencyError, match="invalid-first.*unexecuted-second.*未执行"):
        await tool_rig.registry.middleware().awrap_tool_call(_request(tool_rig, calls, 1), handler)
    assert not handler_called
    assert await tool_rig.operation("invalid-first") is None
    assert await tool_rig.operation("unexecuted-second") is None
    async with tool_rig.factory() as session:
        assert list(await session.scalars(select(FollowUp))) == []


@pytest.mark.anyio
@pytest.mark.parametrize("fault", ["database", "cancellation"])
async def test_prefix_does_not_disguise_database_or_cancellation_as_tool_error(
    tool_rig: ToolRig, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    args = await followup_args(tool_rig)
    calls = [{"name": "crm_follow_up_create", "id": f"call-{i}", "args": args} for i in range(2)]
    error = (
        OperationalError("SELECT", {}, RuntimeError("DB unavailable"))
        if fault == "database"
        else asyncio.CancelledError()
    )

    async def fail(*values, **kwargs):
        raise error

    monkeypatch.setattr(tool_rig.registry, "execute", fail)
    with pytest.raises(type(error)) as caught:
        await tool_rig.registry.middleware().awrap_tool_call(_request(tool_rig, calls, 1), fail)
    assert caught.value is error


@pytest.mark.anyio
@pytest.mark.parametrize("status", [ApprovalStatus.PENDING, ApprovalStatus.REJECTED])
async def test_prefix_only_skips_error_response_if_rejection_is_persisted(
    tool_rig: ToolRig, status: ApprovalStatus
) -> None:
    args = await followup_args(tool_rig)
    await tool_rig.execute(
        "crm_contact_create", {"customer_id": args["customer_id"], "name": "应保留联系人"}, "contact"
    )
    contact_id = await tool_rig.entity_id("contact")
    deletion = {
        "customer_id": args["customer_id"],
        "contact_id": str(contact_id),
        "confirm_customer_name": "图恢复客户",
    }
    await tool_rig.approval("crm_contact_delete", deletion, "delete", status=status)
    calls = [
        {"name": "crm_contact_delete", "id": "delete", "args": deletion},
        {"name": "crm_follow_up_create", "id": "next", "args": args},
    ]
    response = ToolMessage(content="Action rejected", tool_call_id="delete", status="error")

    async def handler(request: ToolCallRequest):
        return await _execute(tool_rig, request)

    invoke = tool_rig.registry.middleware().awrap_tool_call(_request(tool_rig, calls, 1, (response,)), handler)
    if status == ApprovalStatus.PENDING:
        with pytest.raises(AgentToolDependencyError):
            await invoke
        assert await tool_rig.operation("next") is None
    else:
        result = await invoke
        assert result.tool_call_id == "next"
        assert await tool_rig.operation("next") is not None
    async with tool_rig.factory() as session:
        assert await session.get(Contact, contact_id) is not None


@pytest.mark.anyio
async def test_reads_continue_while_write_is_waiting_in_same_batch(tool_rig: ToolRig) -> None:
    args = await followup_args(tool_rig)
    calls = [
        {"name": "crm_follow_up_create", "id": "write", "args": args},
        {"name": "crm_customer_list", "id": "read", "args": {}},
    ]
    read_done = asyncio.Event()

    async def handler(request: ToolCallRequest):
        if request.tool_call["id"] == "write":
            await read_done.wait()
        result = await _execute(tool_rig, request)
        if request.tool_call["id"] == "read":
            read_done.set()
        return result

    middleware = tool_rig.registry.middleware()
    results = await asyncio.wait_for(
        asyncio.gather(*[middleware.awrap_tool_call(_request(tool_rig, calls, i), handler) for i in (0, 1)]), timeout=5
    )
    assert {item.tool_call_id for item in results} == {"write", "read"}
