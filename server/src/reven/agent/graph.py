"""使用 LangChain 原生 Agent 循环；执行端显式采用 sync durability。"""

from collections.abc import Collection, Sequence
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, HumanInTheLoopMiddleware
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph

from reven.agent.context import AgentContext

AgentGraph = CompiledStateGraph[Any, AgentContext, Any, Any]


def build_agent_graph(
    *,
    model: BaseChatModel,
    tools: Sequence[BaseTool],
    system_prompt: str,
    checkpointer: BaseCheckpointSaver[Any],
    middleware: Sequence[AgentMiddleware[Any, AgentContext]] = (),
    confirmation_tools: Collection[str] = (),
) -> AgentGraph:
    tool_names = {tool.name for tool in tools}
    if len(tool_names) != len(tools):
        raise ValueError("Agent 工具名称必须唯一")
    if set(confirmation_tools) - tool_names:
        raise ValueError("确认策略引用了未注册工具")
    policies: list[AgentMiddleware[Any, AgentContext]] = list(middleware)
    if confirmation_tools:
        policies.append(
            HumanInTheLoopMiddleware(
                interrupt_on={name: {"allowed_decisions": ["approve", "reject"]} for name in confirmation_tools}
            )
        )
    return create_agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        checkpointer=checkpointer,
        context_schema=AgentContext,
        middleware=policies,
    )
