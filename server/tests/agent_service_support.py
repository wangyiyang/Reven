"""真实 PostgreSQL AgentService 组合的确定性异步模型替身。"""

import asyncio
from collections.abc import Sequence
from typing import Any, cast

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field
from reven.agent.checkpoint import initialize_checkpoint_schema
from reven.agent.config import AgentConfig
from reven.agent.runtime import AgentRuntime
from reven.agent.service import AgentService
from reven.agent.tool_registry import ToolRegistry
from reven.integrations.credentials import AgentModelEntry, IntegrationCredentials
from reven.integrations.feishu_bot.config import FeishuBotConfig
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

DEFAULT_ENTRY = AgentModelEntry("test-default", "deepseek-official", "deepseek-v4-flash", None, True)
EXTRA_ENTRY = AgentModelEntry("test-extra", "openai", "gpt-5", None, False)
DEFAULT_REF, EXTRA_REF = DEFAULT_ENTRY.ref, EXTRA_ENTRY.ref


class MutableCredentials:
    def __init__(self) -> None:
        self.entries: tuple[AgentModelEntry, ...] | None = (DEFAULT_ENTRY, EXTRA_ENTRY)
        self.whitelist = ("ou_boss", "ou_other")

    async def agent_llm_models(self) -> tuple[AgentModelEntry, ...] | None:
        return self.entries

    async def feishu_bot(self) -> FeishuBotConfig:
        return FeishuBotConfig("test-app", "test-secret", self.whitelist)

    async def config(self, ref: str | None = None) -> AgentConfig | None:
        entry = next(
            (entry for entry in self.entries or () if entry.ref == ref or (ref is None and entry.is_default)), None
        )
        return AgentConfig(entry.provider, entry.model, entry.base_url, entry.api_key) if entry else None


class RigModel(BaseChatModel):
    rig: Any = Field(exclude=True)
    ref: str

    @property
    def _llm_type(self) -> str:
        return "reven-deterministic-test"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "RigModel":
        del tools, kwargs
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        raise AssertionError("运行时必须使用异步模型")

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager, kwargs
        self.rig.calls.append((self.ref, messages))
        if self.ref == self.rig.block_ref:
            self.rig.started.set()
            await self.rig.release.wait()
        if error := self.rig.errors.get(self.ref):
            raise error
        message = messages[-1]
        calls = self.rig.tool_calls.get(message.content, []) if isinstance(message, HumanMessage) else []
        answer = AIMessage(content="" if calls else f"回复@{self.ref}", tool_calls=calls)
        return ChatResult(generations=[ChatGeneration(message=answer)])


class ServiceRig:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self.factory = factory
        self.credentials = MutableCredentials()
        self.calls: list[tuple[str, list[BaseMessage]]] = []
        self.tool_calls: dict[str, list[dict[str, Any]]] = {}
        self.errors: dict[str, Exception] = {}
        self.block_ref: str | None = None
        self.started, self.release = asyncio.Event(), asyncio.Event()
        self.services: list[tuple[AgentService, AgentRuntime]] = []

    async def build(self, *, run_timeout_seconds: float = 180) -> tuple[AgentService, AgentRuntime]:
        engine = self.factory.kw["bind"]
        url = engine.url.render_as_string(hide_password=False)
        await initialize_checkpoint_schema(url)
        config = await self.credentials.config()
        runtime = AgentRuntime(
            config,
            database_url=url,
            registry=ToolRegistry(self.factory),
            config_resolver=self.credentials.config,
            model_resolver=self.credentials.config,
            model_factory=lambda config: RigModel(rig=self, ref=f"{config.provider}/{config.model}"),
            run_timeout_seconds=run_timeout_seconds,
        )
        service = AgentService(runtime, cast(IntegrationCredentials, self.credentials), session_factory=self.factory)
        await service.start()
        self.services.append((service, runtime))
        return service, runtime

    async def close(self) -> None:
        for service, runtime in self.services:
            await service.close()
            await runtime.close()
