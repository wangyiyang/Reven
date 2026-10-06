"""Reven 原生 Agent 核心；避免包导入触发工具或运行时装配。"""

from typing import Any

from reven.agent.config import AgentConfig, resolve_agent_config, resolve_agent_model_config
from reven.agent.errors import AgentError, AgentModelUnavailableError, AgentNotConfiguredError, AgentRuntimeError


def __getattr__(name: str) -> Any:
    if name == "AgentRuntime":
        from reven.agent.runtime import AgentRuntime

        return AgentRuntime
    if name == "AgentService":
        from reven.agent.service import AgentService

        return AgentService
    raise AttributeError(name)


__all__ = [
    "AgentConfig",
    "AgentError",
    "AgentModelUnavailableError",
    "AgentNotConfiguredError",
    "AgentRuntime",
    "AgentRuntimeError",
    "AgentService",
    "resolve_agent_config",
    "resolve_agent_model_config",
]
