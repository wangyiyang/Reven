"""Persist Agent configuration, sessions, runs, approvals and mutation receipts.

Revision ID: 0028_agent_persistence
Revises: 0027_unify_follow_up_channel
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0028_agent_persistence"
down_revision = "0027_unify_follow_up_channel"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _create_revisions()
    _create_sessions()
    _create_runs()
    _create_operations()
    _create_approvals()
    for table in ("agent_config_revisions", "agent_sessions", "agent_runs", "agent_operations", "agent_approvals"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def _create_revisions() -> None:
    op.create_table(
        "agent_config_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("tool_names", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(trim(prompt)) > 0", name="ck_agent_config_revisions_prompt"),
        sa.CheckConstraint("jsonb_typeof(tool_names) = 'array'", name="ck_agent_config_revisions_tools"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version"),
    )


def _create_sessions() -> None:
    op.create_table(
        "agent_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.String(128), nullable=False),
        sa.Column("owner_id", sa.String(256), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("override_model_ref", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("channel IN ('rest', 'feishu')", name="ck_agent_sessions_channel"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_id"),
        sa.UniqueConstraint("id", "owner_id", "channel", name="uq_agent_sessions_identity"),
    )


def _create_runs() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.String(256), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("request_key", sa.String(256), nullable=True),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("model_ref", sa.String(512), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("is_override", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["session_id", "owner_id", "channel"],
            ["agent_sessions.id", "agent_sessions.owner_id", "agent_sessions.channel"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["revision_id"], ["agent_config_revisions.id"]),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'waiting_approval', 'completed', "
            "'failed', 'interrupted', 'needs_reconciliation')",
            name="ck_agent_runs_status",
        ),
        sa.CheckConstraint("jsonb_typeof(snapshot) = 'object'", name="ck_agent_runs_snapshot"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "channel", "request_key", name="uq_agent_runs_request"),
    )
    op.create_index("ix_agent_runs_session_id", "agent_runs", ["session_id"])
    op.create_index("ix_agent_runs_model_ref", "agent_runs", ["model_ref"])
    op.create_index(
        "uq_agent_runs_busy_session",
        "agent_runs",
        ["session_id"],
        unique=True,
        postgresql_where=sa.text("status NOT IN ('completed', 'failed')"),
    )


def _create_operations() -> None:
    op.create_table(
        "agent_operations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("tool_call_id", sa.String(256), nullable=False),
        sa.Column("tool_name", sa.String(128), nullable=False),
        sa.Column("args_hash", sa.String(64), nullable=False),
        sa.Column("args", postgresql.JSONB(), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "tool_call_id", name="uq_agent_operations_run_call"),
        sa.CheckConstraint("status = 'committed'", name="ck_agent_operations_status"),
        sa.CheckConstraint("jsonb_typeof(args) = 'object'", name="ck_agent_operations_args"),
        sa.CheckConstraint("jsonb_typeof(result) = 'object'", name="ck_agent_operations_result"),
    )
    op.create_index("ix_agent_operations_run_id", "agent_operations", ["run_id"])


def _create_approvals() -> None:
    op.create_table(
        "agent_approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("tool_call_id", sa.String(256), nullable=False),
        sa.Column("tool_name", sa.String(128), nullable=False),
        sa.Column("args_hash", sa.String(64), nullable=False),
        sa.Column("args", postgresql.JSONB(), nullable=False),
        sa.Column("target_summary", sa.Text(), nullable=False),
        sa.Column("target_hash", sa.String(64), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "tool_call_id", name="uq_agent_approvals_run_call"),
        sa.CheckConstraint("position >= 0", name="ck_agent_approvals_position"),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'consumed')", name="ck_agent_approvals_status"
        ),
        sa.CheckConstraint("jsonb_typeof(args) = 'object'", name="ck_agent_approvals_args"),
    )
    op.create_index("ix_agent_approvals_run_id", "agent_approvals", ["run_id"])


def downgrade() -> None:
    op.drop_table("agent_approvals")
    op.drop_table("agent_operations")
    op.drop_table("agent_runs")
    op.drop_table("agent_sessions")
    op.drop_table("agent_config_revisions")
