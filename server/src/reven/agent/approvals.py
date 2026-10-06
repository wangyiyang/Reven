"""把图中断映射为可信审批；模型不能创建审批决定。"""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from fastmcp.exceptions import ToolError
from langchain_core.messages import AIMessage
from langgraph.types import Command, StateSnapshot
from sqlalchemy import select

from reven.agent.context import AgentActor
from reven.agent.models import AgentApproval, AgentRun
from reven.agent.persistence_types import (
    AgentApprovalConflictError,
    AgentApprovalNotFoundError,
    AgentStateConflictError,
    ApprovalStatus,
    RunStatus,
    arguments_hash,
)
from reven.agent.repository import AgentRepository
from reven.agent.service_store import AgentStore
from reven.agent.tool_registry import ToolRegistry


@dataclass(frozen=True, slots=True)
class ReviewCall:
    id: str
    name: str
    args: dict[str, object]
    position: int


def review_calls(state: StateSnapshot, registry: ToolRegistry) -> tuple[ReviewCall, ...]:
    interrupts = [item for task in state.tasks for item in task.interrupts]
    if len(interrupts) != 1 or not isinstance(interrupts[0].value, dict):
        raise AgentApprovalConflictError()
    actions = interrupts[0].value.get("action_requests")
    messages = state.values.get("messages", [])
    if not isinstance(actions, list) or not messages or not isinstance(messages[-1], AIMessage):
        raise AgentApprovalConflictError()
    allowed = set(registry.confirmation_tools())
    calls = [call for call in messages[-1].tool_calls if call["name"] in allowed]
    if not calls or len(calls) != len(actions) or len({call["id"] for call in calls}) != len(calls):
        raise AgentApprovalConflictError()
    result = []
    for position, (call, action) in enumerate(zip(calls, actions, strict=True)):
        normalized = registry.canonical_tool_arguments(call["name"], call["args"])
        if (
            not call["id"]
            or not isinstance(action, dict)
            or action.get("name") != call["name"]
            or registry.canonical_tool_arguments(call["name"], action.get("args", {})) != normalized
        ):
            raise AgentApprovalConflictError()
        result.append(ReviewCall(call["id"], call["name"], normalized, position))
    return tuple(result)


def _check_approval(approval: AgentApproval, call: ReviewCall) -> None:
    fingerprint = arguments_hash(call.args)
    if (
        approval.tool_name != call.name
        or approval.args_hash != fingerprint
        or arguments_hash(approval.args) != fingerprint
        or approval.position != call.position
    ):
        raise AgentApprovalConflictError()


class ApprovalCoordinator:
    def __init__(self, store: AgentStore, registry: ToolRegistry) -> None:
        self.store = store
        self.registry = registry

    async def capture(self, run: AgentRun, state: StateSnapshot) -> None:
        calls = review_calls(state, self.registry)
        targets = [await self.registry.confirmation_target(call.name, call.args) for call in calls]
        async with self.store.factory() as db, db.begin():
            repository = AgentRepository(db)
            for call, target in zip(calls, targets, strict=True):
                await repository.create_approval(
                    run.id,
                    owner_id=run.owner_id,
                    tool_call_id=call.id,
                    tool_name=call.name,
                    args=call.args,
                    target_summary=target.summary,
                    target_hash=target.fingerprint,
                    position=call.position,
                )
            if run.status in {RunStatus.INTERRUPTED, RunStatus.NEEDS_RECONCILIATION}:
                await repository.mark_status(run.id, RunStatus.RUNNING, owner_id=run.owner_id)
            await repository.mark_status(run.id, RunStatus.WAITING_APPROVAL, owner_id=run.owner_id)

    async def approval_run(self, approval_id: UUID, session_id: str, actor: AgentActor) -> AgentRun:
        session = await self.store.session(session_id, actor)
        if session is None:
            raise AgentApprovalNotFoundError()
        async with self.store.factory() as db:
            repository = AgentRepository(db)
            approval = await repository.get_approval(approval_id, owner_id=actor.owner_id, session_id=session.id)
            return await repository.get_run(approval.run_id, owner_id=actor.owner_id, session_id=session.id)

    async def decide(
        self, run: AgentRun, state: StateSnapshot, approval_id: UUID, decision: Literal["approve", "reject"]
    ) -> Command[object] | None:
        calls = review_calls(state, self.registry)
        async with self.store.factory() as db, db.begin():
            repository = AgentRepository(db)
            locked = await db.scalar(select(AgentRun).where(AgentRun.id == run.id).with_for_update())
            if locked is None:
                raise AgentStateConflictError()
            if locked.status != RunStatus.WAITING_APPROVAL:
                await repository.resolve_approval(
                    approval_id, decision, owner_id=run.owner_id, session_id=run.session_id
                )
                return None
            rows = await repository.approvals_for_run(run.id, owner_id=run.owner_id)
            by_call = {row.tool_call_id: row for row in rows}
            current = self._ordered_approvals(calls, by_call)
            target = next((row for row in current if row.id == approval_id), None)
            if target is None:
                raise AgentApprovalConflictError()
            if decision == "approve" and target.status != ApprovalStatus.CONSUMED:
                await self._validate_target(target)
            await repository.resolve_approval(approval_id, decision, owner_id=run.owner_id, session_id=run.session_id)
            if any(row.status == ApprovalStatus.PENDING for row in current):
                return None
            await repository.mark_status(run.id, RunStatus.RUNNING, owner_id=run.owner_id)
            return self._command(current)

    async def resume_decisions(self, run: AgentRun, state: StateSnapshot) -> Command[object] | None:
        calls = review_calls(state, self.registry)
        async with self.store.factory() as db:
            rows = await AgentRepository(db).approvals_for_run(run.id, owner_id=run.owner_id)
        current = self._ordered_approvals(calls, {row.tool_call_id: row for row in rows})
        if any(row.status == ApprovalStatus.PENDING for row in current):
            return None
        for row in current:
            if row.status == ApprovalStatus.APPROVED:
                await self._validate_target(row)
        return self._command(current)

    async def _validate_target(self, row: AgentApproval) -> None:
        try:
            fresh = await self.registry.confirmation_target(row.tool_name, row.args)
        except ToolError:
            raise AgentApprovalConflictError() from None
        if fresh.fingerprint != row.target_hash:
            raise AgentApprovalConflictError()

    @staticmethod
    def _ordered_approvals(calls: tuple[ReviewCall, ...], rows: dict[str, AgentApproval]) -> list[AgentApproval]:
        ordered = []
        for call in calls:
            row = rows.get(call.id)
            if row is None:
                raise AgentApprovalConflictError()
            _check_approval(row, call)
            ordered.append(row)
        return ordered

    @staticmethod
    def _command(rows: list[AgentApproval]) -> Command[object]:
        decisions = []
        for row in rows:
            if row.status in {ApprovalStatus.APPROVED, ApprovalStatus.CONSUMED}:
                decisions.append({"type": "approve"})
            elif row.status == ApprovalStatus.REJECTED:
                decisions.append({"type": "reject", "message": "操作者取消了此操作"})
            else:
                raise AgentApprovalConflictError()
        return Command(resume={"decisions": decisions})
