"""REST 与 IM 共享的持久会话、模型选择和后台执行入口。"""

import asyncio
import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any, Literal
from uuid import UUID

from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.agent.approvals import ApprovalCoordinator
from reven.agent.context import ADMIN_ACTOR, AgentActor
from reven.agent.errors import AgentModelUnavailableError, AgentNotConfiguredError, AgentRuntimeError
from reven.agent.execution import RunExecutor, matches_run
from reven.agent.graph import AgentGraph
from reven.agent.model_gate import model_update_guard
from reven.agent.models import AgentRun
from reven.agent.persistence_types import AgentSessionOwnershipError, AgentStateConflictError, RunStatus
from reven.agent.repository import AgentRepository
from reven.agent.runtime import AgentRuntime
from reven.agent.service_store import AgentStore
from reven.agent.service_types import AgentTurn, ConfigurationState, RunState, SessionModelState
from reven.integrations.credentials import IntegrationCredentials

__all__ = ["AgentService", "AgentTurn", "ConfigurationState", "RunState", "SessionModelState"]
logger = logging.getLogger(__name__)


class AgentService:
    def __init__(
        self,
        runtime: AgentRuntime,
        credentials: IntegrationCredentials | None = None,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        wait_timeout_seconds: float = 120,
    ) -> None:
        self._runtime, self._credentials = runtime, credentials
        self._wait_timeout = wait_timeout_seconds
        self._closing = False
        self._admissions = 0
        self._admissions_done = asyncio.Event()
        self._admissions_done.set()
        registry = runtime.registry
        self._store = (
            AgentStore(session_factory, registry.tool_names) if session_factory is not None and registry else None
        )
        self._approvals = ApprovalCoordinator(self._store, registry) if self._store is not None and registry else None
        self._execution = (
            RunExecutor(runtime, self._store, self._approvals) if self._store and self._approvals else None
        )

    @property
    def store(self) -> AgentStore:
        if self._store is None:
            raise AgentRuntimeError("AGENT_RUNTIME_UNAVAILABLE", "Agent 持久化服务尚未就绪")
        return self._store

    @property
    def execution(self) -> RunExecutor:
        if self._execution is None:
            raise AgentRuntimeError("AGENT_RUNTIME_UNAVAILABLE", "Agent 后台执行尚未就绪")
        return self._execution

    @property
    def approvals(self) -> ApprovalCoordinator:
        if self._approvals is None:
            raise AgentRuntimeError("AGENT_RUNTIME_UNAVAILABLE", "Agent 审批服务尚未就绪")
        return self._approvals

    async def start(self) -> None:
        await self._runtime.start()
        if self._store is not None:
            try:
                await self._store.interrupt_stale_runs()
            except Exception as error:
                logger.error("Agent 遗留运行核对失败（error_type=%s）", type(error).__name__)
                await self._runtime.close()

    async def close(self) -> None:
        self._closing = True
        await self._admissions_done.wait()
        if self._execution is not None:
            await self._execution.close()

    def _check_open(self) -> None:
        if self._closing:
            raise AgentRuntimeError("AGENT_SERVICE_CLOSING", "Agent 服务正在关闭")

    @asynccontextmanager
    async def _admission(self) -> AsyncIterator[None]:
        self._check_open()
        self._admissions += 1
        self._admissions_done.clear()
        try:
            yield
        finally:
            self._admissions -= 1
            if self._admissions == 0:
                self._admissions_done.set()

    async def _launch(
        self,
        run: AgentRun,
        *,
        graph: AgentGraph | None = None,
        input_: dict[str, Any] | Command[Any] | None = None,
        new_run: bool = False,
    ) -> None:
        if self._closing:
            await self.store.mark(run, RunStatus.INTERRUPTED, error_code="AGENT_SERVICE_CLOSING")
        else:
            self.execution.launch(run, graph=graph, input_=input_, new_run=new_run)

    async def _authorize(self, actor: AgentActor) -> None:
        if actor.channel == "feishu":
            config = await self._credentials.feishu_bot() if self._credentials is not None else None
            open_id = actor.owner_id.removeprefix("feishu:")
            if config is None or not actor.owner_id.startswith("feishu:") or open_id not in config.whitelist_open_ids:
                raise AgentSessionOwnershipError()

    async def model_refs_in_use(self) -> frozenset[str]:
        return await self.store.model_refs_in_use() if self._store is not None else frozenset()

    def model_update_guard(self) -> AbstractAsyncContextManager[None]:
        return model_update_guard()

    async def model_state(self, session_id: str, *, actor: AgentActor = ADMIN_ACTOR) -> SessionModelState:
        await self._authorize(actor)
        await self._runtime.resolve_config()
        entries = await self._credentials.agent_llm_models() if self._credentials is not None else ()
        available = tuple(entry.ref for entry in entries or ())
        default = self._runtime.default_model_ref
        if default is not None and default not in available:
            available = (default, *available)
        session = await self.store.session(session_id, actor) if self._store is not None else None
        override = session.override_model_ref if session else None
        return SessionModelState(available, default, override or default, override is not None)

    async def use_model(self, session_id: str, model_ref: str, *, actor: AgentActor = ADMIN_ACTOR) -> SessionModelState:
        state = await self.model_state(session_id, actor=actor)
        if model_ref not in state.available_refs or await self._runtime.resolve_config(model_ref) is None:
            raise AgentModelUnavailableError(model_ref)
        await self.store.override(session_id, actor, model_ref if model_ref != state.default_ref else None)
        return await self.model_state(session_id, actor=actor)

    async def get_configuration(self) -> ConfigurationState:
        row = await self.store.configuration()
        return ConfigurationState(row.id, row.version, row.prompt, tuple(row.tool_names))

    async def update_configuration(self, prompt: str, tool_names: Sequence[str]) -> ConfigurationState:
        return await self.store.update_configuration(prompt, tool_names)

    async def get_revision(self, revision_id: UUID) -> ConfigurationState:
        row = await self.store.configuration(revision_id)
        return ConfigurationState(row.id, row.version, row.prompt, tuple(row.tool_names))

    async def history(self, session_id: str, *, actor: AgentActor = ADMIN_ACTOR) -> tuple[RunState, ...]:
        await self._authorize(actor)
        return await self.store.history(session_id, actor)

    async def get_run(
        self, run_id: UUID, *, actor: AgentActor = ADMIN_ACTOR, session_id: str | None = None
    ) -> RunState:
        await self._authorize(actor)
        return await self.store.state(run_id, actor, session_id)

    async def chat(
        self,
        message: str,
        session_id: str | None = None,
        *,
        actor: AgentActor = ADMIN_ACTOR,
        request_key: str | None = None,
        wait_timeout_seconds: float | None = None,
    ) -> AgentTurn:
        self._check_open()
        await self._authorize(actor)
        self._validate_request(message, session_id, request_key)
        if self._store is None and await self._runtime.resolve_config() is None:
            raise AgentNotConfiguredError()
        existing = await self.store.existing_request(message, session_id, actor, request_key)
        if existing is not None:
            return await self._wait_turn(existing.id, actor, wait_timeout_seconds)
        async with self._admission(), self.model_update_guard():
            state = await self.model_state(session_id, actor=actor) if session_id else None
            config = await self._runtime.resolve_config(state.current_ref if state and state.is_override else None)
            if config is None:
                if state and state.is_override:
                    raise AgentModelUnavailableError(state.current_ref or "")
                raise AgentNotConfiguredError()
            claim = await self.store.claim(
                message, session_id, actor, request_key, config, bool(state and state.is_override)
            )
            if claim.created:
                await self._launch(claim.run, new_run=True)
        return await self._wait_turn(claim.run.id, actor, wait_timeout_seconds)

    async def _wait_turn(self, run_id: UUID, actor: AgentActor, timeout: float | None = None) -> AgentTurn:
        await self.execution.wait(run_id, self._wait_timeout if timeout is None else max(0, timeout))
        return self._turn(await self.store.state(run_id, actor))

    @staticmethod
    def _validate_request(message: str, session_id: str | None, key: str | None) -> None:
        if not message.strip() or len(message) > 32000:
            raise AgentRuntimeError("AGENT_INPUT_INVALID", "输入必须为 1 至 32000 字符")
        if (session_id is not None and not 1 <= len(session_id) <= 128) or (
            key is not None and not 1 <= len(key) <= 256
        ):
            raise AgentStateConflictError()

    async def resume_run(
        self,
        run_id: UUID,
        *,
        actor: AgentActor = ADMIN_ACTOR,
        session_id: str | None = None,
        wait_timeout_seconds: float | None = None,
    ) -> AgentTurn:
        await self._authorize(actor)
        async with self._admission(), self.execution.lock(run_id):
            run = await self.store.raw_run(run_id, actor, session_id)
            if run.status not in {RunStatus.QUEUED, RunStatus.RUNNING, RunStatus.COMPLETED, RunStatus.FAILED}:
                graph, _ = await self.execution.prepare(run)
                input_ = await self.execution.resume_input(run, graph)
                if input_ is not False and await self.execution.claim_resume(run):
                    await self._launch(run, graph=graph, input_=input_)
        return await self._wait_turn(run_id, actor, wait_timeout_seconds)

    async def resolve_approval(
        self,
        approval_id: UUID,
        decision: Literal["approve", "reject"],
        session_id: str,
        *,
        actor: AgentActor = ADMIN_ACTOR,
        wait_timeout_seconds: float | None = None,
    ) -> RunState:
        await self._authorize(actor)
        run = await self.approvals.approval_run(approval_id, session_id, actor)
        async with self._admission(), self.execution.lock(run.id):
            run = await self.store.raw_run(run.id, actor, session_id)
            if run.status == RunStatus.WAITING_APPROVAL:
                graph, _ = await self.execution.prepare(run)
                state = await self._runtime.state(graph, run)
                if not matches_run(state, run):
                    raise AgentRuntimeError("AGENT_RECOVERY_UNSAFE", "确认记录缺少一致的原运行检查点")
                command = await self.approvals.decide(run, state, approval_id, decision)
                if command is not None:
                    await self._launch(run, graph=graph, input_=command)
            else:
                await self._repeat_decision(run, approval_id, decision)
        await self.execution.wait(
            run.id, self._wait_timeout if wait_timeout_seconds is None else max(0, wait_timeout_seconds)
        )
        return await self.store.state(run.id, actor, session_id)

    async def _repeat_decision(self, run: AgentRun, approval_id: UUID, decision: Literal["approve", "reject"]) -> None:
        async with self.store.factory() as db, db.begin():
            await AgentRepository(db).resolve_approval(
                approval_id, decision, owner_id=run.owner_id, session_id=run.session_id
            )

    @staticmethod
    def _turn(run: RunState) -> AgentTurn:
        if run.status == RunStatus.COMPLETED:
            text = run.response or ""
        elif run.status == RunStatus.WAITING_APPROVAL:
            rows = [approval for approval in run.approvals if approval.status == "pending"]
            actions = [f"{row.target_summary}\n确认 {row.id}\n取消 {row.id}" for row in rows]
            text = "以下操作需要确认，尚未执行：\n" + "\n\n".join(actions)
        elif run.status in {RunStatus.RUNNING, RunStatus.QUEUED}:
            text = f"运行仍在继续，运行编号：{run.id}。请查询该运行记录，避免重复提交操作。"
        else:
            text = (
                f"运行状态：{run.status}（{run.error_code or 'AGENT_INTERRUPTED'}），运行编号：{run.id}。"
                "请查看已提交操作后恢复原运行。"
            )
        return AgentTurn(run.session_id, text, run.model_ref, run.is_override, run.id)
