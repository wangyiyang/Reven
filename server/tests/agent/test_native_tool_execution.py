import asyncio
from typing import Any

import httpx
import pytest
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command
from native_agent_support import ToolProtocol
from native_transactional_support import checkpoint_pool, followup_args, graph_config, graph_input, native_graph
from reven.agent.context import AgentContext
from reven.agent.executor import ToolExecutor
from reven.agent.models import AgentApproval, AgentOperation
from reven.agent.persistence_types import ApprovalStatus
from reven.agent.tool_definition import ToolDefinition
from reven.agent.tool_registry import ToolRegistry
from reven.crm.models import Contact, FollowUp
from sqlalchemy import select
from tool_execution_support import ToolRig
from tool_execution_support import tool_rig as tool_rig


@pytest.mark.anyio
async def test_real_graph_recovers_commit_before_tool_checkpoint_without_duplicate_followup(
    tool_rig: ToolRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    args = await followup_args(tool_rig)
    original = ToolExecutor._write

    async def lose_after_commit(self: ToolExecutor, *values: Any, **kwargs: Any):
        await original(self, *values, **kwargs)
        raise ConnectionError("业务 COMMIT 后、工具 checkpoint 前中断")

    monkeypatch.setattr(ToolExecutor, "_write", lose_after_commit)
    protocol = ToolProtocol([{"name": "crm_follow_up_create", "id": "stable-call", "args": args}])
    async with httpx.AsyncClient(transport=httpx.MockTransport(protocol)) as client:
        async with checkpoint_pool(tool_rig) as pool:
            graph = native_graph(tool_rig, client, pool)
            with pytest.raises(ConnectionError, match="checkpoint 前"):
                await graph.ainvoke(
                    graph_input(tool_rig), graph_config(tool_rig), context=tool_rig.context, durability="sync"
                )
            assert await tool_rig.operation("stable-call") is not None
        monkeypatch.setattr(ToolExecutor, "_write", original)
        async with checkpoint_pool(tool_rig, cleanup=True) as rebuilt:
            graph = native_graph(tool_rig, client, rebuilt, registry=ToolRegistry(tool_rig.factory))
            state = await graph.aget_state(graph_config(tool_rig))
            assert state.next == ("tools",)
            result = await graph.ainvoke(None, graph_config(tool_rig), context=tool_rig.context, durability="sync")
    assert len([item for item in result["messages"] if isinstance(item, HumanMessage)]) == 1
    assert [item.tool_call_id for item in result["messages"] if isinstance(item, ToolMessage)] == ["stable-call"]
    async with tool_rig.factory() as session:
        assert len(list(await session.scalars(select(FollowUp)))) == 1
        operation = await tool_rig.operation("stable-call")
        assert operation is not None
        assert len([item for item in result["messages"] if isinstance(item, AIMessage) and item.tool_calls]) == 1
    assert len(protocol.requests) == 2


class FailOnlySecondTask(AgentMiddleware[Any, AgentContext]):
    def __init__(self) -> None:
        self.first_completed = asyncio.Event()

    async def awrap_tool_call(self, request: ToolCallRequest, handler):
        if request.tool_call["id"] == "first":
            result = await handler(request)
            self.first_completed.set()
            return result
        await self.first_completed.wait()
        raise ConnectionError("仅后序 task 执行前中断")


class CaptureScheduledTasks(AgentMiddleware[Any, AgentContext]):
    def __init__(self) -> None:
        self.call_ids: list[str] = []

    async def awrap_tool_call(self, request: ToolCallRequest, handler):
        self.call_ids.append(request.tool_call["id"])
        return await handler(request)


@pytest.mark.anyio
async def test_checkpoint_only_reschedules_later_tool_task_and_write_prefix_cannot_deadlock(tool_rig: ToolRig) -> None:
    args = await followup_args(tool_rig)
    calls = [
        {"name": "crm_follow_up_create", "id": "first", "args": {**args, "summary": "前序"}},
        {"name": "crm_follow_up_create", "id": "second", "args": {**args, "summary": "后序"}},
    ]
    protocol = ToolProtocol(calls)
    async with httpx.AsyncClient(transport=httpx.MockTransport(protocol)) as client:
        async with checkpoint_pool(tool_rig) as pool:
            graph = native_graph(tool_rig, client, pool, middleware=[FailOnlySecondTask()])
            with pytest.raises(ConnectionError, match="后序 task"):
                await asyncio.wait_for(
                    graph.ainvoke(
                        graph_input(tool_rig), graph_config(tool_rig), context=tool_rig.context, durability="sync"
                    ),
                    timeout=10,
                )
            assert await tool_rig.operation("first") is not None
            assert await tool_rig.operation("second") is None
        async with checkpoint_pool(tool_rig, cleanup=True) as rebuilt:
            capture = CaptureScheduledTasks()
            graph = native_graph(
                tool_rig, client, rebuilt, registry=ToolRegistry(tool_rig.factory), middleware=[capture]
            )
            result = await asyncio.wait_for(
                graph.ainvoke(None, graph_config(tool_rig), context=tool_rig.context, durability="sync"), timeout=10
            )
            assert capture.call_ids == ["second"]
    messages = [item for item in result["messages"] if isinstance(item, ToolMessage)]
    assert [item.tool_call_id for item in messages] == ["first", "second"]
    async with tool_rig.factory() as session:
        operations = list(
            await session.scalars(
                select(AgentOperation)
                .where(AgentOperation.tool_name == "crm_follow_up_create")
                .order_by(AgentOperation.created_at)
            )
        )
        assert [item.tool_call_id for item in operations] == ["first", "second"]
        assert len(list(await session.scalars(select(FollowUp)))) == 2


async def _mixed_calls(tool_rig: ToolRig):
    args = await followup_args(tool_rig)
    for index in (1, 2):
        await tool_rig.execute(
            "crm_contact_create", {"customer_id": args["customer_id"], "name": f"联系人{index}"}, f"seed-{index}"
        )
    first_id, second_id = await tool_rig.entity_id("seed-1"), await tool_rig.entity_id("seed-2")
    delete = {"customer_id": args["customer_id"], "confirm_customer_name": "图恢复客户"}
    reject_args, approve_args = {**delete, "contact_id": str(first_id)}, {**delete, "contact_id": str(second_id)}
    calls = [
        {"name": "crm_customer_list", "id": "read", "args": {}},
        {"name": "crm_follow_up_create", "id": "before-delete", "args": args},
        {"name": "crm_contact_delete", "id": "rejected-delete", "args": reject_args},
        {"name": "crm_contact_delete", "id": "approved-delete", "args": approve_args},
        {"name": "crm_follow_up_create", "id": "after-delete", "args": {**args, "summary": "批准后继续"}},
    ]
    return calls, first_id, second_id, reject_args, approve_args


@pytest.mark.anyio
async def test_mixed_read_write_and_multiple_delete_decisions_keep_business_order(
    tool_rig: ToolRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls, first_id, second_id, reject_args, approve_args = await _mixed_calls(tool_rig)
    events: list[str] = []
    original = ToolDefinition.invoke

    async def trace_mutations(self: ToolDefinition, values: dict[str, object], *, session=None):
        result = await original(self, values, session=session)
        if self.spec.is_write:
            events.append(self.name)
        return result

    monkeypatch.setattr(ToolDefinition, "invoke", trace_mutations)
    protocol = ToolProtocol(calls)
    async with httpx.AsyncClient(transport=httpx.MockTransport(protocol)) as client:
        async with checkpoint_pool(tool_rig) as pool:
            graph = native_graph(tool_rig, client, pool, confirm=True)
            paused = await graph.ainvoke(
                graph_input(tool_rig), graph_config(tool_rig), context=tool_rig.context, durability="sync"
            )
            assert len(paused["__interrupt__"][0].value["action_requests"]) == 2
            assert events == []
            reject_id = await tool_rig.approval(
                "crm_contact_delete", reject_args, "rejected-delete", status=ApprovalStatus.REJECTED
            )
            approve_id = await tool_rig.approval("crm_contact_delete", approve_args, "approved-delete")
        async with checkpoint_pool(tool_rig, cleanup=True) as rebuilt:
            graph = native_graph(tool_rig, client, rebuilt, registry=ToolRegistry(tool_rig.factory), confirm=True)
            resumed = await graph.ainvoke(
                Command(resume={"decisions": [{"type": "reject", "message": "保留联系人"}, {"type": "approve"}]}),
                graph_config(tool_rig),
                context=tool_rig.context,
                durability="sync",
            )
    assert events == ["crm_follow_up_create", "crm_contact_delete", "crm_follow_up_create"]
    messages = [item for item in resumed["messages"] if isinstance(item, ToolMessage)]
    assert {item.tool_call_id for item in messages} == {item["id"] for item in calls}
    assert next(item for item in messages if item.tool_call_id == "rejected-delete").status == "error"
    async with tool_rig.factory() as session:
        assert await session.get(Contact, first_id) is not None
        assert await session.get(Contact, second_id) is None
        assert len(list(await session.scalars(select(FollowUp)))) == 2
        rejected, approved = await session.get(AgentApproval, reject_id), await session.get(AgentApproval, approve_id)
        assert rejected is not None and rejected.status == ApprovalStatus.REJECTED
        assert approved is not None and approved.status == ApprovalStatus.CONSUMED
