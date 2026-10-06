"""Reven 拥有的 Agent 配置、会话、运行、业务凭据和确认记录。"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from reven.agent.persistence_types import ApprovalStatus, OperationStatus, RunStatus
from reven.db import Base
from reven.scheduling import utc_now


class AgentConfigRevision(Base):
    __tablename__ = "agent_config_revisions"
    __table_args__ = (
        CheckConstraint("length(trim(prompt)) > 0", name="ck_agent_config_revisions_prompt"),
        CheckConstraint("jsonb_typeof(tool_names) = 'array'", name="ck_agent_config_revisions_tools"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    version: Mapped[int] = mapped_column(Integer, Identity(), unique=True)
    prompt: Mapped[str] = mapped_column(Text)
    tool_names: Mapped[list[str]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AgentSession(Base):
    __tablename__ = "agent_sessions"
    __table_args__ = (
        UniqueConstraint("id", "owner_id", "channel", name="uq_agent_sessions_identity"),
        CheckConstraint("channel IN ('rest', 'feishu')", name="ck_agent_sessions_channel"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    external_id: Mapped[str] = mapped_column(String(128), unique=True)
    owner_id: Mapped[str] = mapped_column(String(256))
    channel: Mapped[str] = mapped_column(String(16))
    override_model_ref: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["session_id", "owner_id", "channel"],
            ["agent_sessions.id", "agent_sessions.owner_id", "agent_sessions.channel"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("owner_id", "channel", "request_key", name="uq_agent_runs_request"),
        Index(
            "uq_agent_runs_busy_session",
            "session_id",
            unique=True,
            postgresql_where=text("status NOT IN ('completed', 'failed')"),
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'waiting_approval', 'completed', "
            "'failed', 'interrupted', 'needs_reconciliation')",
            name="ck_agent_runs_status",
        ),
        CheckConstraint("jsonb_typeof(snapshot) = 'object'", name="ck_agent_runs_snapshot"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(index=True)
    owner_id: Mapped[str] = mapped_column(String(256))
    channel: Mapped[str] = mapped_column(String(16))
    request_key: Mapped[str | None] = mapped_column(String(256))
    input_hash: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text)
    revision_id: Mapped[UUID] = mapped_column(ForeignKey("agent_config_revisions.id"))
    snapshot: Mapped[dict[str, object]] = mapped_column(JSONB)
    model_ref: Mapped[str] = mapped_column(String(512), index=True)
    status: Mapped[str] = mapped_column(String(32), default=RunStatus.QUEUED)
    result: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(64))
    is_override: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentOperation(Base):
    __tablename__ = "agent_operations"
    __table_args__ = (
        UniqueConstraint("run_id", "tool_call_id", name="uq_agent_operations_run_call"),
        CheckConstraint("status = 'committed'", name="ck_agent_operations_status"),
        CheckConstraint("jsonb_typeof(args) = 'object'", name="ck_agent_operations_args"),
        CheckConstraint("jsonb_typeof(result) = 'object'", name="ck_agent_operations_result"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True)
    tool_call_id: Mapped[str] = mapped_column(String(256))
    tool_name: Mapped[str] = mapped_column(String(128))
    args_hash: Mapped[str] = mapped_column(String(64))
    args: Mapped[dict[str, object]] = mapped_column(JSONB)
    result: Mapped[dict[str, object]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), default=OperationStatus.COMMITTED)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AgentApproval(Base):
    __tablename__ = "agent_approvals"
    __table_args__ = (
        UniqueConstraint("run_id", "tool_call_id", name="uq_agent_approvals_run_call"),
        CheckConstraint("position >= 0", name="ck_agent_approvals_position"),
        CheckConstraint("status IN ('pending', 'approved', 'rejected', 'consumed')", name="ck_agent_approvals_status"),
        CheckConstraint("jsonb_typeof(args) = 'object'", name="ck_agent_approvals_args"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True)
    tool_call_id: Mapped[str] = mapped_column(String(256))
    tool_name: Mapped[str] = mapped_column(String(128))
    args_hash: Mapped[str] = mapped_column(String(64))
    args: Mapped[dict[str, object]] = mapped_column(JSONB)
    target_summary: Mapped[str] = mapped_column(Text)
    target_hash: Mapped[str] = mapped_column(String(64))
    position: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default=ApprovalStatus.PENDING)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
