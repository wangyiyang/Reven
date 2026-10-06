import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from langchain.tools import ToolRuntime
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from native_agent_support import ToolProtocol
from reven.agent.checkpoint import AgentCheckpoints, initialize_checkpoint_schema
from reven.agent.context import AgentContext
from reven.agent.graph import AgentGraph, build_agent_graph
from reven.agent.providers import build_chat_model


def _context() -> AgentContext:
    return AgentContext(owner_id="test-admin", session_id=uuid4(), run_id=uuid4())


def _config(context: AgentContext) -> dict[str, Any]:
    return {
        "configurable": {"thread_id": str(context.session_id)},
        "metadata": {"reven_run_id": str(context.run_id)},
        "recursion_limit": 20,
    }


def _model(client: httpx.AsyncClient) -> BaseChatModel:
    return build_chat_model("deepseek-official", "deepseek-v4-flash", None, "test-key", http_async_client=client)


def _followup_tool(events: list[tuple[UUID, str, AgentContext, str | None]], *, fail: bool = False) -> BaseTool:
    async def follow_up(customer_id: UUID, summary: str, runtime: ToolRuntime[AgentContext]) -> str:
        """为指定客户记录跟进。"""
        if fail:
            raise RuntimeError("执行前中断")
        events.append((customer_id, summary, runtime.context, runtime.tool_call_id))
        return "已记录客户跟进"

    return StructuredTool.from_function(coroutine=follow_up, name="crm_follow_up_create")


def _delete_tool(events: list[tuple[UUID, AgentContext, str | None]]) -> BaseTool:
    async def delete_customer(customer_id: UUID, runtime: ToolRuntime[AgentContext]) -> str:
        """删除指定客户及其联系人和跟进。"""
        events.append((customer_id, runtime.context, runtime.tool_call_id))
        return "已删除客户"

    return StructuredTool.from_function(coroutine=delete_customer, name="crm_customer_delete")


def _graph(model: BaseChatModel, tool: BaseTool, pool: AgentCheckpoints, *, confirm: bool = False) -> AgentGraph:
    return build_agent_graph(
        model=model,
        tools=[tool],
        system_prompt="使用业务工具完成请求，删除必须经过人工批准。",
        checkpointer=pool.saver,
        confirmation_tools=[tool.name] if confirm else (),
    )


@asynccontextmanager
async def _checkpoints(context: AgentContext, *, cleanup: bool = False) -> AsyncIterator[AgentCheckpoints]:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL 未设置，跳过 PostgreSQL 检查点测试")
    await initialize_checkpoint_schema(url)
    pool = AgentCheckpoints(url)
    await pool.open()
    try:
        yield pool
    finally:
        if cleanup:
            await pool.saver.adelete_thread(str(context.session_id))
        await pool.close()
        assert not await pool.ready()


@pytest.mark.anyio
async def test_postgres_tool_loop_restores_history_reasoning_and_trusted_context() -> None:
    context, customer_id = _context(), uuid4()
    events: list[tuple[UUID, str, AgentContext, str | None]] = []
    protocol = ToolProtocol(
        [
            {
                "name": "crm_follow_up_create",
                "id": "followup-1",
                "args": {"customer_id": str(customer_id), "summary": "已电话跟进"},
            }
        ]
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(protocol)) as client:
        async with _checkpoints(context) as pool:
            graph = _graph(_model(client), _followup_tool(events), pool)
            result = await graph.ainvoke(
                {"messages": [HumanMessage(content="记录客户跟进", id=str(context.run_id))]},
                _config(context),
                context=context,
                durability="sync",
            )
            assert result["messages"][-1].content == "已完成"
            assert events == [(customer_id, "已电话跟进", context, "followup-1")]
            schema = protocol.requests[0]["tools"][0]["function"]["parameters"]
            assert set(schema["properties"]) == {"customer_id", "summary"}
        async with _checkpoints(context, cleanup=True) as rebuilt:
            graph = _graph(_model(client), _followup_tool(events), rebuilt)
            state = await graph.aget_state(_config(context))
            assert [type(message) for message in state.values["messages"]] == [
                HumanMessage,
                AIMessage,
                ToolMessage,
                AIMessage,
            ]
            assert state.values["messages"][1].additional_kwargs["reasoning_content"] == "先调用业务工具"
            assert state.metadata["reven_run_id"] == str(context.run_id)
            await graph.ainvoke(
                {"messages": [HumanMessage(content="复述历史")]}, _config(context), context=context, durability="sync"
            )
    assert len(events) == 1
    assert protocol.requests[-1]["messages"][2]["reasoning_content"] == "先调用业务工具"
    assert protocol.requests[-1]["messages"][3]["tool_call_id"] == "followup-1"


@pytest.mark.anyio
async def test_postgres_human_review_survives_pool_and_graph_rebuild_with_ordered_decisions() -> None:
    context, first, second = _context(), uuid4(), uuid4()
    events: list[tuple[UUID, AgentContext, str | None]] = []
    calls = [
        {"name": "crm_customer_delete", "id": call_id, "args": {"customer_id": str(customer)}}
        for call_id, customer in [("delete-first", first), ("delete-second", second)]
    ]
    protocol = ToolProtocol(calls)
    async with httpx.AsyncClient(transport=httpx.MockTransport(protocol)) as client:
        async with _checkpoints(context) as pool:
            graph = _graph(_model(client), _delete_tool(events), pool, confirm=True)
            paused = await graph.ainvoke(
                {"messages": [HumanMessage(content="删除两个客户")]},
                _config(context),
                context=context,
                durability="sync",
            )
            interrupt = paused["__interrupt__"][0]
            assert [action["args"]["customer_id"] for action in interrupt.value["action_requests"]] == [
                str(first),
                str(second),
            ]
            assert all(
                review["allowed_decisions"] == ["approve", "reject"] for review in interrupt.value["review_configs"]
            )
            assert events == []
        async with _checkpoints(context, cleanup=True) as rebuilt:
            graph = _graph(_model(client), _delete_tool(events), rebuilt, confirm=True)
            state = await graph.aget_state(_config(context))
            assert state.tasks[0].interrupts[0].id == interrupt.id
            result = await graph.ainvoke(
                Command(resume={"decisions": [{"type": "reject", "message": "取消第一个"}, {"type": "approve"}]}),
                _config(context),
                context=context,
                durability="sync",
            )
            assert "__interrupt__" not in result
            assert events == [(second, context, "delete-second")]
            messages = [message for message in result["messages"] if isinstance(message, ToolMessage)]
            assert [message.tool_call_id for message in messages] == ["delete-first", "delete-second"]
            assert messages[0].status == "error"
    assert protocol.requests[1]["messages"][2]["reasoning_content"] == "先调用业务工具"


@pytest.mark.anyio
async def test_postgres_ordinary_interruption_resumes_without_appending_input_or_new_call_ids() -> None:
    context, customer_id = _context(), uuid4()
    events: list[tuple[UUID, str, AgentContext, str | None]] = []
    protocol = ToolProtocol(
        [
            {
                "name": "crm_follow_up_create",
                "id": "resume-call",
                "args": {"customer_id": str(customer_id), "summary": "恢复记录"},
            }
        ]
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(protocol)) as client:
        async with _checkpoints(context) as pool:
            graph = _graph(_model(client), _followup_tool(events, fail=True), pool)
            with pytest.raises(RuntimeError, match="执行前中断"):
                await graph.ainvoke(
                    {"messages": [HumanMessage(content="记录客户跟进", id=str(context.run_id))]},
                    _config(context),
                    context=context,
                    durability="sync",
                )
            assert events == []
        async with _checkpoints(context, cleanup=True) as rebuilt:
            graph = _graph(_model(client), _followup_tool(events), rebuilt)
            state = await graph.aget_state(_config(context))
            assert state.next == ("tools",)
            result = await graph.ainvoke(None, _config(context), context=context, durability="sync")
            assert len([message for message in result["messages"] if isinstance(message, HumanMessage)]) == 1
            assert events == [(customer_id, "恢复记录", context, "resume-call")]
    assert len(protocol.requests) == 2


@pytest.mark.anyio
async def test_human_review_cannot_edit_tool_or_arguments() -> None:
    context = _context()
    events: list[tuple[UUID, AgentContext, str | None]] = []
    protocol = ToolProtocol(
        [{"name": "crm_customer_delete", "id": "delete-fixed", "args": {"customer_id": str(uuid4())}}]
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(protocol)) as client:
        graph = build_agent_graph(
            model=_model(client),
            tools=[_delete_tool(events)],
            system_prompt="删除客户",
            checkpointer=InMemorySaver(),
            confirmation_tools=["crm_customer_delete"],
        )
        await graph.ainvoke(
            {"messages": [HumanMessage(content="删除客户")]}, _config(context), context=context, durability="sync"
        )
        with pytest.raises(ValueError):
            await graph.ainvoke(
                Command(
                    resume={
                        "decisions": [
                            {
                                "type": "edit",
                                "edited_action": {"name": "crm_customer_delete", "args": {"customer_id": str(uuid4())}},
                            }
                        ]
                    }
                ),
                _config(context),
                context=context,
                durability="sync",
            )
    assert events == []


def test_confirmation_policy_cannot_reference_missing_tools() -> None:
    model = build_chat_model("deepseek-official", "deepseek-v4-flash", None, "test-key")
    with pytest.raises(ValueError, match="未注册工具"):
        build_agent_graph(
            model=model,
            tools=[],
            system_prompt="助手",
            checkpointer=InMemorySaver(),
            confirmation_tools=["missing_tool"],
        )
