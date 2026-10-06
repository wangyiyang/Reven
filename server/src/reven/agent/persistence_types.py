"""Agent 持久状态、参数指纹与稳定错误。"""

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from typing import TYPE_CHECKING, cast
from uuid import UUID

from reven.agent.errors import AgentError

if TYPE_CHECKING:
    from reven.agent.models import AgentRun


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    NEEDS_RECONCILIATION = "needs_reconciliation"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CONSUMED = "consumed"


class OperationStatus(StrEnum):
    COMMITTED = "committed"


TERMINAL_RUN_STATUSES = (RunStatus.COMPLETED, RunStatus.FAILED)
BUSY_RUN_STATUSES = tuple(status for status in RunStatus if status not in TERMINAL_RUN_STATUSES)
_RUN_TRANSITIONS = {
    RunStatus.QUEUED: {RunStatus.RUNNING, RunStatus.INTERRUPTED, RunStatus.FAILED, RunStatus.NEEDS_RECONCILIATION},
    RunStatus.RUNNING: set(RunStatus) - {RunStatus.QUEUED},
    RunStatus.WAITING_APPROVAL: {RunStatus.RUNNING, RunStatus.FAILED, RunStatus.NEEDS_RECONCILIATION},
    RunStatus.INTERRUPTED: {RunStatus.RUNNING, RunStatus.FAILED, RunStatus.NEEDS_RECONCILIATION},
    RunStatus.NEEDS_RECONCILIATION: {RunStatus.RUNNING, RunStatus.FAILED},
    RunStatus.COMPLETED: set(),
    RunStatus.FAILED: set(),
}


@dataclass(frozen=True)
class RunClaim:
    run: "AgentRun"
    created: bool


class AgentPersistenceError(AgentError):
    """数据库业务冲突；消息不得包含凭据或数据库异常原文。"""


class AgentSessionOwnershipError(AgentPersistenceError):
    def __init__(self) -> None:
        super().__init__("AGENT_SESSION_FORBIDDEN", "会话不存在或不可访问")


class AgentRunNotFoundError(AgentPersistenceError):
    def __init__(self) -> None:
        super().__init__("AGENT_RUN_NOT_FOUND", "运行记录不存在或不可访问")


class AgentRequestConflictError(AgentPersistenceError):
    def __init__(self) -> None:
        super().__init__("AGENT_REQUEST_CONFLICT", "该请求编号已用于其他会话或输入")


class AgentSessionBusyError(AgentPersistenceError):
    def __init__(self, run_id: UUID) -> None:
        super().__init__("AGENT_SESSION_BUSY", f"会话仍有未完成运行：{run_id}")
        self.run_id = run_id


class AgentStateConflictError(AgentPersistenceError):
    def __init__(self) -> None:
        super().__init__("AGENT_STATE_CONFLICT", "当前运行状态不允许该操作")


class AgentApprovalNotFoundError(AgentPersistenceError):
    def __init__(self) -> None:
        super().__init__("AGENT_APPROVAL_NOT_FOUND", "确认记录不存在或不可访问")


class AgentApprovalConflictError(AgentPersistenceError):
    def __init__(self) -> None:
        super().__init__("AGENT_APPROVAL_CONFLICT", "确认记录与原操作或已有决定不一致")


def validate_run_transition(current: str, target: RunStatus) -> None:
    if current != target and target not in _RUN_TRANSITIONS[RunStatus(current)]:
        raise AgentStateConflictError()


def _json_default(value: object) -> str:
    if isinstance(value, (UUID, Decimal)):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError("Agent 参数必须是可序列化的 JSON 值")


def canonical_arguments(arguments: dict[str, object]) -> dict[str, object]:
    return cast(dict[str, object], json.loads(_canonical_json(arguments)))


def arguments_hash(arguments: dict[str, object]) -> str:
    return sha256(_canonical_json(arguments).encode("utf-8")).hexdigest()


def message_hash(message: str) -> str:
    return sha256(message.encode("utf-8")).hexdigest()


def _canonical_json(value: dict[str, object]) -> str:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False, default=_json_default
    )
