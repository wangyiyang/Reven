"""应用拥有的后台执行与恢复；请求等待超时不会取消图。"""

import asyncio
import logging
from typing import Any, Literal
from uuid import UUID

from langchain_core.messages import HumanMessage
from langgraph.types import Command, StateSnapshot
from sqlalchemy import select

from reven.agent.approvals import ApprovalCoordinator
from reven.agent.config import AgentConfig
from reven.agent.context import AgentActor
from reven.agent.errors import AgentError, AgentModelUnavailableError, AgentRuntimeError
from reven.agent.graph import AgentGraph
from reven.agent.models import AgentRun
from reven.agent.persistence_types import AgentStateConflictError, RunStatus
from reven.agent.repository import AgentRepository
from reven.agent.runtime import AgentRuntime, final_response
from reven.agent.service_store import AgentStore

logger = logging.getLogger(__name__)


def has_interrupt(state: StateSnapshot) -> bool:
    return any(task.interrupts for task in state.tasks)


def matches_run(state: StateSnapshot, run: AgentRun) -> bool:
    metadata = state.metadata or {}
    return (
        metadata.get("reven_run_id") == str(run.id)
        and metadata.get("reven_revision_id") == str(run.revision_id)
        and any(
            isinstance(message, HumanMessage) and message.id == str(run.id)
            for message in state.values.get("messages", [])
        )
    )


class RunExecutor:
    def __init__(self, runtime: AgentRuntime, store: AgentStore, approvals: ApprovalCoordinator) -> None:
        self.runtime, self.store, self.approvals = runtime, store, approvals
        self.tasks: dict[UUID, asyncio.Task[None]] = {}
        self.locks: dict[UUID, asyncio.Lock] = {}
        self._closing = False

    def lock(self, run_id: UUID) -> asyncio.Lock:
        return self.locks.setdefault(run_id, asyncio.Lock())

    async def close(self) -> None:
        self._closing = True
        tasks = tuple(self.tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.tasks.clear()
        self.locks.clear()

    async def prepare(self, run: AgentRun) -> tuple[AgentGraph, AgentConfig]:
        config = await self.runtime.resolve_config(run.model_ref)
        if config is None:
            raise AgentModelUnavailableError(run.model_ref)
        revision = await self.store.configuration(run.revision_id)
        current = await self.store.configuration()
        if not set(revision.tool_names) <= set(current.tool_names):
            raise AgentRuntimeError("AGENT_TOOL_DISABLED", "原运行的工具已停用，不能继续执行")
        return self.runtime.build_graph(run, revision, config), config

    def launch(
        self,
        run: AgentRun,
        *,
        graph: AgentGraph | None = None,
        input_: dict[str, Any] | Command[Any] | None = None,
        new_run: bool = False,
    ) -> None:
        if self._closing:
            raise AgentRuntimeError("AGENT_SERVICE_CLOSING", "Agent 服务正在关闭")
        if run.id in self.tasks:
            return
        task = asyncio.create_task(self._execute(run, graph, input_, new_run), name=f"reven-agent-{run.id}")
        self.tasks[run.id] = task
        task.add_done_callback(lambda done: self._task_done(run.id, done))

    def _task_done(self, run_id: UUID, task: asyncio.Task[None]) -> None:
        if self.tasks.get(run_id) is task:
            self.tasks.pop(run_id, None)
        if not task.cancelled() and task.exception() is not None:
            logger.error("Agent 状态持久化失败（run_id=%s, error_type=%s）", run_id, type(task.exception()).__name__)

    async def wait(self, run_id: UUID, timeout: float) -> None:
        task = self.tasks.get(run_id)
        if task is None:
            return
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
        except TimeoutError:
            return

    async def _execute(
        self, run: AgentRun, graph: AgentGraph | None, input_: dict[str, Any] | Command[Any] | None, new_run: bool
    ) -> None:
        invoked = False
        try:
            # claim 之后再次现读，模型已被删除时不会向图提交输入。
            prepared, _ = await self.prepare(run)
            graph = prepared
            if new_run:
                await self.store.mark(run, RunStatus.RUNNING)
                input_ = {"messages": [HumanMessage(content=run.message, id=str(run.id))]}
            invoked = True
            result = await self.runtime.invoke(graph, run, input_)
            if result.get("__interrupt__"):
                await self.approvals.capture(run, await self.runtime.state(graph, run))
            else:
                await self.store.mark(run, RunStatus.COMPLETED, response=final_response(result))
        except asyncio.CancelledError:
            await self._record_failure(run, graph, invoked, new_run, "AGENT_EXECUTION_CANCELLED")
            raise
        except Exception as error:
            code = error.code if isinstance(error, AgentError) else "AGENT_EXECUTION_FAILED"
            if isinstance(error, TimeoutError):
                code = "AGENT_EXECUTION_TIMEOUT"
            logger.warning(
                "Agent 执行中断（run_id=%s, error_type=%s, error_code=%s）", run.id, type(error).__name__, code
            )
            await self._record_failure(run, graph, invoked, new_run, code)

    async def _record_failure(
        self, run: AgentRun, graph: AgentGraph | None, invoked: bool, new_run: bool, code: str
    ) -> None:
        if not invoked:
            await self.store.mark(run, RunStatus.FAILED if new_run else RunStatus.NEEDS_RECONCILIATION, error_code=code)
            return
        try:
            if graph is None:
                raise AgentStateConflictError()
            state = await self.runtime.state(graph, run)
            if matches_run(state, run):
                if not state.next and not has_interrupt(state):
                    response = final_response(state.values)
                    await self.store.mark(run, RunStatus.COMPLETED, response=response)
                    return
                status = RunStatus.NEEDS_RECONCILIATION if has_interrupt(state) else RunStatus.INTERRUPTED
            else:
                # sync durability 下，未接受本轮输入且没有业务凭据才可安全结束新运行。
                actor = AgentActor(run.owner_id, run.channel)  # type: ignore[arg-type]
                operations = (await self.store.state(run.id, actor)).operations
                status = RunStatus.FAILED if new_run and not operations else RunStatus.NEEDS_RECONCILIATION
        except Exception as error:
            logger.warning("Agent 恢复状态无法核实（run_id=%s, error_type=%s）", run.id, type(error).__name__)
            status = RunStatus.NEEDS_RECONCILIATION
        await self.store.mark(run, status, error_code=code)

    async def resume_input(self, run: AgentRun, graph: AgentGraph) -> Command[Any] | None | Literal[False]:
        state = await self.runtime.state(graph, run)
        if not matches_run(state, run):
            await self.store.mark(run, RunStatus.NEEDS_RECONCILIATION, error_code="AGENT_CHECKPOINT_MISMATCH")
            raise AgentRuntimeError("AGENT_RECOVERY_UNSAFE", "缺少与原运行一致的检查点，请先核对业务凭据")
        if has_interrupt(state):
            if run.status != RunStatus.WAITING_APPROVAL:
                await self.approvals.capture(run, state)
            command = await self.approvals.resume_decisions(run, state)
            return command if command is not None else False
        if not state.next:
            await self.store.complete_checkpoint(run, final_response(state.values))
            return False
        if not state.tasks:
            await self.store.mark(run, RunStatus.NEEDS_RECONCILIATION, error_code="AGENT_CHECKPOINT_INCOMPLETE")
            raise AgentRuntimeError("AGENT_RECOVERY_UNSAFE", "检查点没有可恢复的任务")
        return None

    async def claim_resume(self, run: AgentRun) -> bool:
        async with self.store.factory() as db, db.begin():
            repository = AgentRepository(db)
            current = await db.scalar(select(AgentRun).where(AgentRun.id == run.id).with_for_update())
            if current is None:
                raise AgentStateConflictError()
            if current.status == RunStatus.RUNNING:
                return False
            if current.status not in {
                RunStatus.INTERRUPTED,
                RunStatus.NEEDS_RECONCILIATION,
                RunStatus.WAITING_APPROVAL,
            }:
                raise AgentStateConflictError()
            await repository.mark_status(run.id, RunStatus.RUNNING, owner_id=run.owner_id)
            return True
