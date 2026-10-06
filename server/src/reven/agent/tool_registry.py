"""Derive native Agent and read-only machine adapters from one explicit catalog."""

import inspect
from collections.abc import Iterable
from functools import wraps
from typing import cast

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from langchain.tools import ToolRuntime
from langchain_core.tools import BaseTool, StructuredTool
from langchain_core.tools.base import create_schema_from_function
from pydantic import BaseModel, ConfigDict, create_model
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.agent.context import AgentContext
from reven.agent.executor import ToolExecutor
from reven.agent.tool_binding import ToolSessionBinding
from reven.agent.tool_catalog import TOOL_SPECS
from reven.agent.tool_confirmations import ConfirmationTarget, confirmation_target
from reven.agent.tool_definition import AsyncToolFunction, BindingFactory, ToolDefinition, ToolSpec
from reven.agent.tool_errors import AgentToolContextError
from reven.agent.tool_ordering import ToolExecutionMiddleware
from reven.agent.tools_rss import KeywordEmbeddingHooks, RssKeywordTools


class ToolRegistry:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        embedding_refresher: KeywordEmbeddingHooks | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._embedding_refresher = embedding_refresher
        self._executor = ToolExecutor(session_factory, embedding_refresher=embedding_refresher)
        self.definitions = {spec.name: self._definition(spec) for spec in TOOL_SPECS}

    @property
    def tool_names(self) -> tuple[str, ...]:
        return tuple(self.definitions)

    def is_write(self, tool_name: str) -> bool:
        definition = self.definitions.get(tool_name)
        return definition is not None and definition.spec.is_write

    def canonical_tool_arguments(self, tool_name: str, arguments: dict[str, object]) -> dict[str, object]:
        return self.definitions[tool_name].canonical_arguments(arguments)

    def confirmation_tools(self, tool_names: Iterable[str] | None = None) -> tuple[str, ...]:
        return tuple(
            definition.name for definition in self._selected(tool_names) if definition.spec.requires_confirmation
        )

    async def confirmation_target(self, tool_name: str, arguments: dict[str, object]) -> ConfirmationTarget:
        definition = self.definitions[tool_name]
        if not definition.spec.requires_confirmation:
            raise ToolError("该工具不需要人工确认")
        normalized = definition.canonical_arguments(arguments)
        async with self._session_factory() as session:
            return await confirmation_target(session, tool_name, normalized)

    async def execute(
        self, tool_name: str, arguments: dict[str, object], context: AgentContext, tool_call_id: str
    ) -> object:
        return await self._executor.execute(self.definitions[tool_name], arguments, context, tool_call_id)

    async def is_rejected_call(
        self, tool_name: str, arguments: dict[str, object], context: AgentContext, tool_call_id: str
    ) -> bool:
        return await self._executor.is_rejected_call(self.definitions[tool_name], arguments, context, tool_call_id)

    def native_tools(self, tool_names: Iterable[str] | None = None) -> list[BaseTool]:
        return [self._native(definition) for definition in self._selected(tool_names)]

    def middleware(self) -> ToolExecutionMiddleware:
        return ToolExecutionMiddleware(self)

    def register_mcp(self, mcp: FastMCP) -> None:
        for definition in self.definitions.values():
            mcp.tool(self._machine_adapter(definition), name=definition.name)

    def _selected(self, tool_names: Iterable[str] | None) -> list[ToolDefinition]:
        if tool_names is None:
            return list(self.definitions.values())
        names = tuple(tool_names)
        if len(set(names)) != len(names) or set(names) - self.definitions.keys():
            raise ValueError("工具配置包含重复或未知名称")
        return [self.definitions[name] for name in names]

    def _definition(self, spec: ToolSpec) -> ToolDefinition:
        binder = self._binder(spec)
        _, function = binder(None)
        schema = cast(type[BaseModel], create_schema_from_function(spec.name, function))
        schema.model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)
        schema.model_rebuild(force=True)
        return ToolDefinition(spec, function, schema, inspect.getdoc(function) or spec.name, binder)

    def _binder(self, spec: ToolSpec) -> BindingFactory:
        def bind(session: AsyncSession | None) -> tuple[ToolSessionBinding, AsyncToolFunction]:
            if spec.owner is RssKeywordTools:
                binding: ToolSessionBinding = RssKeywordTools(
                    self._session_factory, self._embedding_refresher, session=session
                )
            else:
                binding = spec.owner(self._session_factory, session=session)
            return binding, cast(AsyncToolFunction, getattr(binding, spec.method))

        return bind

    def _native(self, definition: ToolDefinition) -> StructuredTool:
        async def invoke(runtime: ToolRuntime[AgentContext], **arguments: object) -> object:
            if not isinstance(runtime.context, AgentContext) or runtime.tool_call_id is None:
                raise AgentToolContextError()
            return await self._executor.execute(definition, arguments, runtime.context, runtime.tool_call_id)

        schema = create_model(
            f"{definition.name}NativeInput", __base__=definition.args_schema, runtime=(ToolRuntime[AgentContext], ...)
        )
        return StructuredTool.from_function(
            coroutine=invoke,
            name=definition.name,
            description=definition.description,
            args_schema=schema,
        )

    @staticmethod
    def _machine_adapter(definition: ToolDefinition) -> AsyncToolFunction:
        @wraps(definition.source)
        async def invoke(**arguments: object) -> object:
            if definition.spec.is_write:
                raise ToolError("MCP_WRITE_CONTEXT_REQUIRED：写操作必须通过已认证的 Agent 运行入口")
            output, _ = await definition.invoke(arguments)
            return output

        return invoke
