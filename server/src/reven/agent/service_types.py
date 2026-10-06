"""入口共享的公开 Agent 状态，均不携带模型凭据。"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class SessionModelState:
    available_refs: tuple[str, ...]
    default_ref: str | None
    current_ref: str | None
    is_override: bool
    pending_default_ref: str | None = None


@dataclass(frozen=True, slots=True)
class AgentTurn:
    session_id: str
    response: str
    model_ref: str | None
    is_override: bool
    run_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class ConfigurationState:
    id: UUID
    version: int
    prompt: str
    tool_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ApprovalState:
    id: UUID
    tool_call_id: str
    tool_name: str
    args: dict[str, object]
    target_summary: str
    status: str


@dataclass(frozen=True, slots=True)
class OperationState:
    id: UUID
    tool_call_id: str
    tool_name: str
    args: dict[str, object]
    result: dict[str, object]


@dataclass(frozen=True, slots=True)
class RunState:
    id: UUID
    session_id: str
    status: str
    response: str | None
    model_ref: str
    is_override: bool
    error_code: str | None
    approvals: tuple[ApprovalState, ...]
    operations: tuple[OperationState, ...]
    created_at: datetime
    updated_at: datetime
    message: str = ""
