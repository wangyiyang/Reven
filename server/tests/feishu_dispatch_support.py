"""飞书入口测试替身与异步回复等待。"""

import asyncio
import time
from typing import Literal
from uuid import UUID

from agent_api_support import RUN, RUN_ID
from reven.agent.context import AgentActor
from reven.agent.errors import AgentModelUnavailableError, AgentNotConfiguredError
from reven.agent.service_types import AgentTurn, RunState, SessionModelState
from reven.integrations.feishu_bot.chat_dispatcher import FeishuChatDispatcher
from reven.integrations.feishu_bot.config import FeishuBotConfig

DEFAULT_REF = "deepseek-official/deepseek-v4-flash"
EXTRA_REF = "deepseek-official/deepseek-v4-pro"


class StubCredentials:
    def __init__(self) -> None:
        self.config = FeishuBotConfig(
            app_id="cli_test", app_secret="test-secret", whitelist_open_ids=("ou_boss", "ou_other")
        )

    async def feishu_bot(self) -> FeishuBotConfig | None:
        return self.config


class ReplyRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, message_id: str, text: str) -> None:
        self.calls.append((message_id, text))


class FeishuAgentStub:
    def __init__(self) -> None:
        self.refs = (DEFAULT_REF, EXTRA_REF)
        self.default_ref: str | None = DEFAULT_REF
        self.overrides: dict[str, str] = {}
        self.chat_calls: list[tuple[object, ...]] = []
        self.command_calls: list[tuple[object, ...]] = []
        self.command_wait_timeouts: list[float | None] = []
        self.errors: dict[str, Exception] = {}
        self.run = RUN
        self.command_error: Exception | None = None

    async def model_state(self, session_id: str, *, actor: AgentActor) -> SessionModelState:
        self.command_calls.append(("model_state", session_id, actor))
        override = self.overrides.get(session_id)
        return SessionModelState(self.refs, self.default_ref, override or self.default_ref, override is not None)

    async def use_model(self, session_id: str, model_ref: str, *, actor: AgentActor) -> SessionModelState:
        self.command_calls.append(("use_model", session_id, model_ref, actor))
        if model_ref not in self.refs:
            raise AgentModelUnavailableError(model_ref)
        if model_ref == self.default_ref:
            self.overrides.pop(session_id, None)
        else:
            self.overrides[session_id] = model_ref
        return await self.model_state(session_id, actor=actor)

    async def chat(
        self,
        message: str,
        session_id: str | None = None,
        *,
        actor: AgentActor,
        request_key: str | None = None,
        wait_timeout_seconds: float | None = None,
    ) -> AgentTurn:
        self.chat_calls.append((message, session_id, actor, request_key, wait_timeout_seconds))
        state = await self.model_state(session_id or "", actor=actor)
        if state.current_ref is None:
            raise AgentNotConfiguredError()
        if state.current_ref not in self.refs:
            raise AgentModelUnavailableError(state.current_ref)
        if state.current_ref in self.errors:
            raise self.errors[state.current_ref]
        return AgentTurn(session_id or "", f"回复@{state.current_ref}", state.current_ref, state.is_override, RUN_ID)

    def _record_command(self, *args: object) -> None:
        self.command_calls.append(args)
        if self.command_error:
            raise self.command_error

    async def get_run(self, run_id: UUID, *, actor: AgentActor, session_id: str | None = None) -> RunState:
        self._record_command("get_run", run_id, actor, session_id)
        return self.run

    async def resolve_approval(
        self,
        approval_id: UUID,
        decision: Literal["approve", "reject"],
        session_id: str,
        *,
        actor: AgentActor,
        wait_timeout_seconds: float | None = None,
    ) -> RunState:
        self.command_wait_timeouts.append(wait_timeout_seconds)
        self._record_command("resolve_approval", approval_id, decision, session_id, actor)
        return self.run

    async def resume_run(
        self,
        run_id: UUID,
        *,
        actor: AgentActor,
        session_id: str | None = None,
        wait_timeout_seconds: float | None = None,
    ) -> AgentTurn:
        self.command_wait_timeouts.append(wait_timeout_seconds)
        self._record_command("resume_run", run_id, actor, session_id)
        return AgentTurn(session_id or "", "已继续原运行", DEFAULT_REF, False, run_id)


async def submit(dispatcher: FeishuChatDispatcher, text: str, **kwargs: str) -> None:
    params = {"message_id": "om_1", "chat_id": "oc_1", "open_id": "ou_boss", **kwargs}
    await asyncio.to_thread(dispatcher.submit, kind="chat", text=text, **params)


async def wait_replies(recorder: ReplyRecorder, count: int) -> None:
    deadline = time.monotonic() + 5
    while len(recorder.calls) < count and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
    assert len(recorder.calls) >= count, recorder.calls
