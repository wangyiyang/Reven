"""Serialize a batch's business writes without waiting for skipped graph tasks."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any
from weakref import WeakValueDictionary

from fastmcp.exceptions import ToolError
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import AIMessage, ToolCall, ToolMessage
from langgraph.types import Command
from pydantic import ValidationError

from reven.agent.context import AgentContext
from reven.agent.tool_errors import AgentToolContextError, AgentToolDependencyError

if TYPE_CHECKING:
    from reven.agent.tool_registry import ToolRegistry


class ToolExecutionMiddleware(AgentMiddleware[Any, AgentContext]):
    def __init__(self, registry: "ToolRegistry") -> None:
        self._registry = registry
        self._locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        if not self._registry.is_write(request.tool_call["name"]):
            return await handler(request)
        context = request.runtime.context
        if not isinstance(context, AgentContext):
            raise AgentToolContextError()
        key = str(context.run_id)
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            previous = self._write_prefix(request)
            for call, response in previous:
                if response is not None:
                    if response.status == "error" and not await self._registry.is_rejected_call(
                        call["name"], call["args"], context, call["id"]
                    ):
                        raise AgentToolDependencyError(call["id"], request.tool_call["id"])
                    continue
                try:
                    await self._registry.execute(call["name"], call["args"], context, call["id"])
                except (ToolError, ValidationError) as exc:
                    raise AgentToolDependencyError(call["id"], request.tool_call["id"]) from exc
            return await handler(request)

    def _write_prefix(self, request: ToolCallRequest) -> list[tuple[ToolCall, ToolMessage | None]]:
        messages = request.state.get("messages", []) if isinstance(request.state, dict) else []
        for index in range(len(messages) - 1, -1, -1):
            message = messages[index]
            if isinstance(message, AIMessage):
                responses = {item.tool_call_id: item for item in messages[index + 1 :] if isinstance(item, ToolMessage)}
                prefix: list[tuple[ToolCall, ToolMessage | None]] = []
                for call in message.tool_calls:
                    call_id = call["id"]
                    if call_id is None:
                        raise AgentToolContextError()
                    if call_id == request.tool_call["id"]:
                        return prefix
                    if not self._registry.is_write(call["name"]):
                        continue
                    prefix.append((call, responses.get(call_id)))
                break
        raise AgentToolContextError()
