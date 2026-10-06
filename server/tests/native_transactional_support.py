import os
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

import httpx
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage
from reven.agent.checkpoint import AgentCheckpoints, initialize_checkpoint_schema
from reven.agent.context import AgentContext
from reven.agent.graph import AgentGraph, build_agent_graph
from reven.agent.providers import build_chat_model
from reven.agent.tool_registry import ToolRegistry
from tool_execution_support import ToolRig


def graph_config(rig: ToolRig) -> dict[str, Any]:
    return {
        "configurable": {"thread_id": str(rig.context.session_id)},
        "metadata": {"reven_run_id": str(rig.context.run_id)},
        "recursion_limit": 20,
    }


def graph_input(rig: ToolRig) -> dict[str, object]:
    return {"messages": [HumanMessage(content="执行经营操作", id=str(rig.context.run_id))]}


def native_graph(
    rig: ToolRig,
    client: httpx.AsyncClient,
    pool: AgentCheckpoints,
    *,
    registry: ToolRegistry | None = None,
    middleware: Sequence[AgentMiddleware[Any, AgentContext]] = (),
    confirm: bool = False,
) -> AgentGraph:
    tools = registry or rig.registry
    return build_agent_graph(
        model=build_chat_model("deepseek-official", "deepseek-v4-flash", None, "test-key", http_async_client=client),
        tools=tools.native_tools(),
        system_prompt="使用工具执行操作，删除须批准。",
        checkpointer=pool.saver,
        middleware=[*middleware, tools.middleware()],
        confirmation_tools=tools.confirmation_tools() if confirm else (),
    )


@asynccontextmanager
async def checkpoint_pool(rig: ToolRig, *, cleanup: bool = False) -> AsyncIterator[AgentCheckpoints]:
    url = os.environ["TEST_DATABASE_URL"]
    await initialize_checkpoint_schema(url)
    pool = AgentCheckpoints(url)
    await pool.open()
    try:
        yield pool
    finally:
        if cleanup:
            await pool.saver.adelete_thread(str(rig.context.session_id))
        await pool.close()


async def followup_args(rig: ToolRig) -> dict[str, object]:
    await rig.execute("crm_customer_create", {"name": "图恢复客户"}, "seed-customer")
    return {
        "customer_id": str(await rig.entity_id("seed-customer")),
        "kind": "电话",
        "occurred_on": "2026-10-06",
        "summary": "确认合作",
    }
