"""Run a deterministic native Agent against the isolated self-host PostgreSQL."""

import asyncio
import importlib.metadata
import os
from typing import Any
from uuid import UUID, uuid4

from langchain.tools import ToolRuntime, tool
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langsmith import tracing_context
from reven.agent.checkpoint import AgentCheckpoints
from reven.agent.context import AgentContext
from reven.agent.graph import build_agent_graph


class SmokeModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "isolated-self-host-smoke"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "SmokeModel":
        return self

    def _generate(
        self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> ChatResult:
        if isinstance(messages[-1], HumanMessage):
            reply = AIMessage(
                content="",
                tool_calls=[{"id": str(uuid4()), "name": "record_smoke", "args": {"note": "isolated fixture"}}],
            )
        else:
            reply = AIMessage(content="smoke completed")
        return ChatResult(generations=[ChatGeneration(message=reply)])


async def main() -> None:
    assert not any(
        dist.metadata.get("Name", "").startswith("deepseek-harness") for dist in importlib.metadata.distributions()
    )
    if thread_id := os.environ.get("REVEN_SMOKE_THREAD"):
        await verify_persisted_thread(UUID(thread_id))
        return
    session_id = uuid4()
    executions: list[str] = []

    @tool
    async def record_smoke(note: str, runtime: ToolRuntime[AgentContext]) -> str:
        """Record one isolated smoke step; no business data is changed."""
        assert runtime.context.owner_id == "self-host-smoke"
        assert runtime.context.session_id == session_id
        assert runtime.tool_call_id
        executions.append(note)
        return "recorded"

    configuration = {"configurable": {"thread_id": str(session_id)}}
    checkpoints = AgentCheckpoints(os.environ["DATABASE_URL"])
    try:
        for step in range(2):
            await checkpoints.open()
            graph = build_agent_graph(
                model=SmokeModel(), tools=[record_smoke], system_prompt="isolated smoke", checkpointer=checkpoints.saver
            )
            context = AgentContext("self-host-smoke", session_id, uuid4())
            result = await graph.ainvoke(
                {"messages": [HumanMessage(content=f"smoke step {step}")]},
                configuration,
                context=context,
                durability="sync",
            )
            assert result["messages"][-1].content == "smoke completed"
            assert len(result["messages"]) == 4 * (step + 1)
            await graph.ainvoke(None, configuration, context=context, durability="sync")
            assert len(executions) == step + 1
            await checkpoints.close()
        print("Native Agent tools, PostgreSQL history and pool reconstruction verified")
        print(session_id)
    finally:
        await checkpoints.close()


async def verify_persisted_thread(thread_id: UUID) -> None:
    checkpoints = AgentCheckpoints(os.environ["DATABASE_URL"])
    try:
        await checkpoints.open()
        saved = await checkpoints.saver.aget_tuple({"configurable": {"thread_id": str(thread_id)}})
        assert saved is not None
        assert len(saved.checkpoint["channel_values"]["messages"]) == 8
        print("Native Agent persisted history verified")
    finally:
        await checkpoints.close()


if __name__ == "__main__":
    with tracing_context(enabled=False):
        asyncio.run(main())
