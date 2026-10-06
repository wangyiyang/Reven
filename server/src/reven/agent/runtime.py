"""原生异步图与检查点生命周期，不拥有业务会话或审批状态。"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, cast

import httpx
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command, StateSnapshot
from langsmith import tracing_context

from reven.agent.checkpoint import AgentCheckpoints
from reven.agent.config import AgentConfig
from reven.agent.context import AgentContext
from reven.agent.errors import AgentModelUnavailableError, AgentRuntimeError
from reven.agent.graph import AgentGraph, build_agent_graph
from reven.agent.model_guard import ModelErrorBoundary
from reven.agent.models import AgentConfigRevision, AgentRun
from reven.agent.providers import build_chat_model
from reven.integrations.providers import model_ref_of

if TYPE_CHECKING:
    from reven.agent.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)
ModelConfigResolver = Callable[[str], Awaitable[AgentConfig | None]]
DefaultConfigResolver = Callable[[], Awaitable[AgentConfig | None]]
ChatModelFactory = Callable[[AgentConfig], BaseChatModel]


def graph_config(run: AgentRun) -> RunnableConfig:
    return {
        "configurable": {"thread_id": str(run.session_id)},
        "metadata": {"reven_run_id": str(run.id), "reven_revision_id": str(run.revision_id)},
        "recursion_limit": 60,
    }


def final_response(values: dict[str, Any]) -> str:
    messages = values.get("messages", [])
    if not messages or not isinstance(messages[-1], AIMessage) or messages[-1].tool_calls:
        raise AgentRuntimeError("AGENT_RESPONSE_INCOMPLETE", "Agent 尚未生成最终结果")
    content = messages[-1].content
    if isinstance(content, str):
        return content
    return "".join(
        block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text"
    )


class AgentRuntime:
    def __init__(
        self,
        config: AgentConfig | None,
        *,
        database_url: str | None = None,
        registry: "ToolRegistry | None" = None,
        config_resolver: DefaultConfigResolver | None = None,
        model_resolver: ModelConfigResolver | None = None,
        model_factory: ChatModelFactory | None = None,
        run_timeout_seconds: float = 180,
    ) -> None:
        self._config = config
        self.registry = registry
        self._config_resolver = config_resolver
        self._model_resolver = model_resolver
        self._model_factory = model_factory
        self._run_timeout_seconds = run_timeout_seconds
        self.checkpoints = AgentCheckpoints(database_url) if database_url is not None else None
        self._available = False
        self._http: httpx.AsyncClient | None = None
        self._sync_http: httpx.Client | None = None

    @property
    def configured(self) -> bool:
        return self._config is not None

    @property
    def available(self) -> bool:
        return self._available

    @property
    def default_model_ref(self) -> str | None:
        return model_ref_of(self._config.provider, self._config.model) if self._config else None

    async def resolve_config(self, model_ref: str | None = None) -> AgentConfig | None:
        self._config = await self._config_resolver() if self._config_resolver else self._config
        if model_ref is None:
            return self._config
        if self._model_resolver is not None:
            return await self._model_resolver(model_ref)
        return self._config if model_ref == self.default_model_ref else None

    async def start(self) -> None:
        if self.available or self.checkpoints is None:
            return
        try:
            await self.checkpoints.open()
            self._http = httpx.AsyncClient(timeout=60, trust_env=False)
            self._sync_http = httpx.Client(timeout=60, trust_env=False)
            self._available = True
        except Exception as error:
            logger.error("Agent 初始化失败，运行时降级（error_type=%s）", type(error).__name__)

    async def close(self) -> None:
        self._available = False
        if self._http is not None:
            await self._http.aclose()
            self._http = None
        if self._sync_http is not None:
            self._sync_http.close()
            self._sync_http = None
        if self.checkpoints is not None:
            await self.checkpoints.close()

    def build_graph(self, run: AgentRun, revision: AgentConfigRevision, config: AgentConfig) -> AgentGraph:
        if not self.available or self.checkpoints is None or self.registry is None:
            raise AgentRuntimeError("AGENT_RUNTIME_UNAVAILABLE", "Agent 检查点或工具尚未就绪")
        if model_ref_of(config.provider, config.model) != run.model_ref:
            raise AgentModelUnavailableError(run.model_ref, "原运行模型配置不一致")
        frozen = run.snapshot
        if (
            frozen.get("runtime_contract") != 1
            or frozen.get("provider") != config.provider
            or frozen.get("model") != config.model
            or frozen.get("base_url") != config.base_url
            or frozen.get("tool_names") != revision.tool_names
        ):
            raise AgentRuntimeError("AGENT_CONFIG_CHANGED", "原运行配置已变化，不能继续执行")
        model = (
            self._model_factory(config)
            if self._model_factory
            else build_chat_model(
                config.provider,
                config.model,
                config.base_url,
                config.api_key,
                http_async_client=self._http,
                http_client=self._sync_http,
            )
        )
        return build_agent_graph(
            model=model,
            tools=self.registry.native_tools(revision.tool_names),
            system_prompt=revision.prompt,
            checkpointer=self.checkpoints.saver,
            middleware=[ModelErrorBoundary(), self.registry.middleware()],
            confirmation_tools=self.registry.confirmation_tools(revision.tool_names),
        )

    async def invoke(
        self, graph: AgentGraph, run: AgentRun, input_: dict[str, Any] | Command[Any] | None
    ) -> dict[str, Any]:
        context = AgentContext(run.owner_id, run.session_id, run.id)
        with tracing_context(enabled=False):
            async with asyncio.timeout(self._run_timeout_seconds):
                return cast(
                    dict[str, Any], await graph.ainvoke(input_, graph_config(run), context=context, durability="sync")
                )

    async def state(self, graph: AgentGraph, run: AgentRun) -> StateSnapshot:
        return await graph.aget_state(graph_config(run))
