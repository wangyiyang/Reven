"""add finance_entries table

Revision ID: 0010
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "finance_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("due_on", sa.Date(), nullable=True),
        sa.Column("recurrence", sa.String(length=32), nullable=True),
        sa.Column("source", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_finance_entries_kind", "finance_entries", ["kind"])
    op.create_index("ix_finance_entries_category", "finance_entries", ["category"])
    op.create_index("ix_finance_entries_occurred_on", "finance_entries", ["occurred_on"])
    op.create_index("ix_finance_entries_status", "finance_entries", ["status"])
    op.execute("ALTER TABLE finance_entries ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_finance_entries_status", table_name="finance_entries")
    op.drop_index("ix_finance_entries_occurred_on", table_name="finance_entries")
    op.drop_index("ix_finance_entries_category", table_name="finance_entries")
    op.drop_index("ix_finance_entries_kind", table_name="finance_entries")
    op.drop_table("finance_entries")
