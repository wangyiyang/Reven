"""Agent 数据访问；调用者拥有事务，不在模型等待期间持有连接。"""

from collections.abc import Sequence
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import exists, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from reven.agent.models import AgentApproval, AgentConfigRevision, AgentRun, AgentSession
from reven.agent.persistence_types import (
    BUSY_RUN_STATUSES,
    TERMINAL_RUN_STATUSES,
    AgentApprovalConflictError,
    AgentApprovalNotFoundError,
    AgentPersistenceError,
    AgentRequestConflictError,
    AgentRunNotFoundError,
    AgentSessionBusyError,
    AgentSessionOwnershipError,
    AgentStateConflictError,
    ApprovalStatus,
    RunClaim,
    RunStatus,
    arguments_hash,
    canonical_arguments,
    message_hash,
    validate_run_transition,
)
from reven.scheduling import utc_now

_CONFIG_LOCK = 1776330323
_SECRET_FIELDS = {"api_key", "encrypted_secret", "secret", "password", "authorization", "token", "app_secret"}


class AgentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def ensure_session(self, external_id: str, *, owner_id: str, channel: str) -> AgentSession:
        if not (1 <= len(external_id) <= 128 and 1 <= len(owner_id) <= 256) or channel not in {"rest", "feishu"}:
            raise AgentSessionOwnershipError()
        statement = insert(AgentSession).values(external_id=external_id, owner_id=owner_id, channel=channel)
        await self.session.execute(statement.on_conflict_do_nothing(index_elements=[AgentSession.external_id]))
        row = await self.session.scalar(select(AgentSession).where(AgentSession.external_id == external_id))
        if row is None or row.owner_id != owner_id or row.channel != channel:
            raise AgentSessionOwnershipError()
        return row

    async def get_session(self, session_id: UUID, *, owner_id: str) -> AgentSession:
        row = await self.session.scalar(
            select(AgentSession).where(AgentSession.id == session_id, AgentSession.owner_id == owner_id)
        )
        if row is None:
            raise AgentSessionOwnershipError()
        return row

    async def find_session(self, external_id: str, *, owner_id: str, channel: str) -> AgentSession | None:
        row: AgentSession | None = await self.session.scalar(
            select(AgentSession).where(AgentSession.external_id == external_id)
        )
        if row is not None and (row.owner_id != owner_id or row.channel != channel):
            raise AgentSessionOwnershipError()
        return row

    async def set_override(self, session_id: UUID, model_ref: str | None, *, owner_id: str) -> AgentSession:
        row = await self.get_session(session_id, owner_id=owner_id)
        row.override_model_ref = model_ref
        await self.session.flush()
        return row

    async def current_revision(self, *, default_prompt: str, default_tool_names: Sequence[str]) -> AgentConfigRevision:
        row = await self._current_revision()
        if row is not None:
            return row
        await self._lock_configuration()
        row = await self._current_revision()
        if row is None:
            row = await self._insert_revision(default_prompt, default_tool_names)
        return row

    async def get_revision(self, revision_id: UUID) -> AgentConfigRevision:
        row = await self.session.get(AgentConfigRevision, revision_id)
        if row is None:
            raise AgentPersistenceError("AGENT_REVISION_NOT_FOUND", "Agent 配置版本不存在")
        return row

    async def create_revision(self, *, prompt: str, tool_names: Sequence[str]) -> AgentConfigRevision:
        await self._lock_configuration()
        return await self._insert_revision(prompt, tool_names)

    async def _current_revision(self) -> AgentConfigRevision | None:
        row: AgentConfigRevision | None = await self.session.scalar(
            select(AgentConfigRevision).order_by(AgentConfigRevision.version.desc()).limit(1)
        )
        return row

    async def _lock_configuration(self) -> None:
        await self.session.execute(select(func.pg_advisory_xact_lock(_CONFIG_LOCK)))

    async def _insert_revision(self, prompt: str, tool_names: Sequence[str]) -> AgentConfigRevision:
        if (
            not prompt.strip()
            or len(tool_names) != len(set(tool_names))
            or any(not name.strip() for name in tool_names)
        ):
            raise AgentPersistenceError("AGENT_CONFIG_INVALID", "Agent 指令不能为空，工具名称必须唯一且非空")
        row = AgentConfigRevision(prompt=prompt, tool_names=list(tool_names))
        self.session.add(row)
        await self.session.flush()
        return row

    async def find_request_run(self, *, owner_id: str, channel: str, request_key: str) -> AgentRun | None:
        row: AgentRun | None = await self.session.scalar(
            select(AgentRun).where(
                AgentRun.owner_id == owner_id, AgentRun.channel == channel, AgentRun.request_key == request_key
            )
        )
        return row

    async def create_run(
        self,
        *,
        session: AgentSession,
        revision: AgentConfigRevision,
        message: str,
        model_ref: str,
        snapshot: dict[str, object],
        is_override: bool,
        request_key: str | None = None,
    ) -> RunClaim:
        if request_key is not None:
            if not 1 <= len(request_key) <= 256:
                raise AgentRequestConflictError()
            existing = await self.find_request_run(
                owner_id=session.owner_id, channel=session.channel, request_key=request_key
            )
            if existing is not None:
                return self._reuse_run(existing, session.id, message)
        await self.session.execute(select(AgentSession.id).where(AgentSession.id == session.id).with_for_update())
        if request_key is not None:
            existing = await self.find_request_run(
                owner_id=session.owner_id, channel=session.channel, request_key=request_key
            )
            if existing is not None:
                return self._reuse_run(existing, session.id, message)
        busy = await self.session.scalar(
            select(AgentRun.id).where(AgentRun.session_id == session.id, AgentRun.status.in_(BUSY_RUN_STATUSES))
        )
        if busy is not None:
            raise AgentSessionBusyError(busy)
        run_id = uuid4()
        values = self._run_values(session, revision, message, model_ref, snapshot, is_override, request_key, run_id)
        statement = insert(AgentRun).values(**values).on_conflict_do_nothing(constraint="uq_agent_runs_request")
        row = await self.session.scalar(statement.returning(AgentRun))
        if row is not None:
            return RunClaim(row, True)
        existing = await self.find_request_run(
            owner_id=session.owner_id, channel=session.channel, request_key=request_key or ""
        )
        if existing is None:
            raise AgentRequestConflictError()
        return self._reuse_run(existing, session.id, message)

    @staticmethod
    def _reuse_run(row: AgentRun, session_id: UUID, message: str) -> RunClaim:
        if row.session_id != session_id or row.input_hash != message_hash(message):
            raise AgentRequestConflictError()
        return RunClaim(row, False)

    @staticmethod
    def _run_values(
        session: AgentSession,
        revision: AgentConfigRevision,
        message: str,
        model_ref: str,
        snapshot: dict[str, object],
        is_override: bool,
        request_key: str | None,
        run_id: UUID,
    ) -> dict[str, object]:
        _reject_snapshot_secrets(snapshot)
        return {
            "id": run_id,
            "session_id": session.id,
            "owner_id": session.owner_id,
            "channel": session.channel,
            "request_key": request_key,
            "input_hash": message_hash(message),
            "message": message,
            "revision_id": revision.id,
            "snapshot": canonical_arguments(snapshot),
            "model_ref": model_ref,
            "is_override": is_override,
        }

    async def get_run(self, run_id: UUID, *, owner_id: str, session_id: UUID | None = None) -> AgentRun:
        statement = select(AgentRun).where(AgentRun.id == run_id, AgentRun.owner_id == owner_id)
        if session_id is not None:
            statement = statement.where(AgentRun.session_id == session_id)
        row = await self.session.scalar(statement)
        if row is None:
            raise AgentRunNotFoundError()
        return row

    async def list_runs(self, session_id: UUID, *, owner_id: str, limit: int = 50) -> list[AgentRun]:
        await self.get_session(session_id, owner_id=owner_id)
        statement = (
            select(AgentRun)
            .where(AgentRun.session_id == session_id, AgentRun.owner_id == owner_id)
            .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
            .limit(limit)
        )
        return list(await self.session.scalars(statement))

    async def mark_status(
        self,
        run_id: UUID,
        status: RunStatus,
        *,
        owner_id: str,
        result: str | None = None,
        error_code: str | None = None,
    ) -> AgentRun:
        row = await self._locked_run(run_id, owner_id)
        validate_run_transition(row.status, status)
        if row.status == status:
            return row
        row.status = status
        row.error_code = error_code
        if status == RunStatus.COMPLETED:
            row.result = result
        if status in TERMINAL_RUN_STATUSES:
            row.completed_at = utc_now()
        await self.session.flush()
        return row

    async def _locked_run(self, run_id: UUID, owner_id: str) -> AgentRun:
        statement = (
            select(AgentRun)
            .where(AgentRun.id == run_id, AgentRun.owner_id == owner_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        row = await self.session.scalar(statement)
        if row is None:
            raise AgentRunNotFoundError()
        return row

    async def create_approval(
        self,
        run_id: UUID,
        *,
        owner_id: str,
        tool_call_id: str,
        tool_name: str,
        args: dict[str, object],
        target_summary: str,
        target_hash: str,
        position: int = 0,
    ) -> AgentApproval:
        run = await self._locked_run(run_id, owner_id)
        if run.status in TERMINAL_RUN_STATUSES:
            raise AgentStateConflictError()
        values = {
            "run_id": run_id,
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "args_hash": arguments_hash(args),
            "args": canonical_arguments(args),
            "target_summary": target_summary,
            "target_hash": target_hash,
            "position": position,
        }
        statement = insert(AgentApproval).values(**values)
        statement = statement.on_conflict_do_nothing(constraint="uq_agent_approvals_run_call")
        await self.session.execute(statement)
        row = await self.session.scalar(
            select(AgentApproval).where(AgentApproval.run_id == run_id, AgentApproval.tool_call_id == tool_call_id)
        )
        fields = ("tool_name", "args_hash", "target_summary", "target_hash", "position")
        if row is None or any(getattr(row, field) != values[field] for field in fields):
            raise AgentApprovalConflictError()
        return row

    async def get_approval(self, approval_id: UUID, *, owner_id: str, session_id: UUID | None = None) -> AgentApproval:
        statement = (
            select(AgentApproval).join(AgentRun).where(AgentApproval.id == approval_id, AgentRun.owner_id == owner_id)
        )
        if session_id is not None:
            statement = statement.where(AgentRun.session_id == session_id)
        row = await self.session.scalar(statement)
        if row is None:
            raise AgentApprovalNotFoundError()
        return row

    async def approvals_for_run(
        self, run_id: UUID, *, owner_id: str, pending_only: bool = False
    ) -> list[AgentApproval]:
        await self.get_run(run_id, owner_id=owner_id)
        statement = select(AgentApproval).where(AgentApproval.run_id == run_id)
        if pending_only:
            statement = statement.where(AgentApproval.status == ApprovalStatus.PENDING)
        return list(await self.session.scalars(statement.order_by(AgentApproval.position, AgentApproval.id)))

    async def resolve_approval(
        self,
        approval_id: UUID,
        decision: Literal["approve", "reject"],
        *,
        owner_id: str,
        session_id: UUID,
    ) -> AgentApproval:
        if decision not in {"approve", "reject"}:
            raise AgentApprovalConflictError()
        approval = await self.get_approval(approval_id, owner_id=owner_id, session_id=session_id)
        run = await self._locked_run(approval.run_id, owner_id)
        await self.session.refresh(approval, with_for_update=True)
        target = ApprovalStatus.APPROVED if decision == "approve" else ApprovalStatus.REJECTED
        if approval.status == target or (decision == "approve" and approval.status == ApprovalStatus.CONSUMED):
            return approval
        if approval.status != ApprovalStatus.PENDING:
            raise AgentApprovalConflictError()
        if run.status != RunStatus.WAITING_APPROVAL:
            raise AgentStateConflictError()
        approval.status = target
        approval.decided_at = utc_now()
        await self.session.flush()
        return approval

    async def model_refs_in_use(self) -> tuple[str, ...]:
        pending = exists().where(AgentApproval.run_id == AgentRun.id, AgentApproval.status == ApprovalStatus.PENDING)
        statement = select(AgentRun.model_ref).where(AgentRun.status.in_(BUSY_RUN_STATUSES) | pending).distinct()
        return tuple(await self.session.scalars(statement.order_by(AgentRun.model_ref)))

    async def interrupt_stale_runs(self) -> int:
        statement = (
            update(AgentRun)
            .where(AgentRun.status.in_((RunStatus.RUNNING, RunStatus.QUEUED)))
            .values(status=RunStatus.INTERRUPTED, updated_at=utc_now())
            .returning(AgentRun.id)
        )
        return len(list(await self.session.scalars(statement)))


def _reject_snapshot_secrets(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in _SECRET_FIELDS:
                raise AgentPersistenceError("AGENT_SNAPSHOT_INVALID", "Agent 配置快照不得保存凭据")
            _reject_snapshot_secrets(child)
    elif isinstance(value, list):
        for child in value:
            _reject_snapshot_secrets(child)
