"""Agent 业务入口：会话模型选择、实际默认与本轮执行身份。"""

import logging
from dataclasses import dataclass, replace

from reven.agent.errors import AgentError, AgentModelUnavailableError
from reven.agent.runtime import AgentRuntime
from reven.integrations.credentials import IntegrationCredentials

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SessionModelState:
    available_refs: tuple[str, ...]
    default_ref: str | None
    current_ref: str | None
    is_override: bool
    pending_default_ref: str | None


@dataclass(frozen=True, slots=True)
class AgentTurn:
    session_id: str
    response: str
    model_ref: str | None
    is_override: bool


class AgentService:
    """REST 与 IM 共享的会话业务；选择按外部 session_id 在主循环内存持有。"""

    def __init__(self, runtime: AgentRuntime, credentials: IntegrationCredentials | None = None) -> None:
        self._runtime = runtime
        self._credentials = credentials
        self._overrides: dict[str, str] = {}

    def model_refs_in_use(self) -> frozenset[str]:
        """主循环中读取会话选择快照，供模型删除保护使用。"""
        return frozenset(self._overrides.values())

    async def model_state(self, session_id: str) -> SessionModelState:
        entries = await self._credentials.agent_llm_models() if self._credentials is not None else None
        available_refs = tuple(entry.ref for entry in entries or ())
        default_ref = self._runtime.default_model_ref
        if default_ref is not None and default_ref not in available_refs:
            available_refs = (default_ref, *available_refs)
        saved_default = next((entry.ref for entry in entries or () if entry.is_default), None)
        override = self._overrides.get(session_id)
        return SessionModelState(
            available_refs=available_refs,
            default_ref=default_ref,
            current_ref=override or default_ref,
            is_override=override is not None,
            pending_default_ref=saved_default if saved_default != default_ref else None,
        )

    async def use_model(self, session_id: str, model_ref: str) -> SessionModelState:
        state = await self.model_state(session_id)
        if model_ref not in state.available_refs:
            raise AgentModelUnavailableError(model_ref)
        is_override = model_ref != state.default_ref
        if is_override:
            self._overrides[session_id] = model_ref
        else:
            self._overrides.pop(session_id, None)
        return replace(state, current_ref=model_ref, is_override=is_override)

    async def chat(self, message: str, session_id: str | None = None) -> AgentTurn:
        override = self._overrides.get(session_id) if session_id is not None else None
        model_ref = override or self._runtime.default_model_ref
        try:
            active_id, response = await self._runtime.chat(message, session_id, model=override)
        except AgentModelUnavailableError:
            raise
        except AgentError as exc:
            if override is None:
                raise
            logger.warning(
                "会话模型调用失败（model=%s, error_type=%s, error_code=%s）",
                override,
                type(exc).__name__,
                exc.code,
            )
            raise AgentModelUnavailableError(override, "调用失败") from exc
        return AgentTurn(active_id, response, model_ref, override is not None)
