"""add talents and talent interactions

Revision ID: 0015_talents
Revises: 0014_merge_crm_and_integration
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0015_talents"
down_revision = "0014_merge_crm_and_integration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _create_talents()
    _create_talent_interactions()


def _create_talents() -> None:
    op.create_table(
        "talents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("organization", sa.Text(), nullable=True),
        sa.Column(
            "tags",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("capability", sa.Text(), nullable=True),
        sa.Column("engagement_terms", sa.Text(), nullable=True),
        sa.Column("availability", sa.Text(), nullable=True),
        sa.Column("rate_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("rate_unit", sa.String(length=16), nullable=True),
        sa.Column("rating", sa.SmallInteger(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default=sa.text("'候选'"), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("jsonb_typeof(tags) = 'array'", name="ck_talents_tags_array"),
        sa.CheckConstraint("rate_unit IN ('按小时', '按天', '按项目')", name="ck_talents_rate_unit"),
        sa.CheckConstraint("rating BETWEEN 1 AND 5", name="ck_talents_rating_range"),
        sa.CheckConstraint("(rate_amount IS NULL) = (rate_unit IS NULL)", name="ck_talents_rate_pair"),
        sa.CheckConstraint("status IN ('候选', '接洽中', '已合作', '搁置')", name="ck_talents_status"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_talents_status", "talents", ["status"])
    op.execute("ALTER TABLE talents ENABLE ROW LEVEL SECURITY")


def _create_talent_interactions() -> None:
    op.create_table(
        "talent_interactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("talent_id", sa.Uuid(), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("next_action", sa.Text(), nullable=True),
        sa.Column("next_due_on", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "channel IN ('面谈', '电话语音', '微信', '邮件')",
            name="ck_talent_interactions_channel",
        ),
        sa.ForeignKeyConstraint(["talent_id"], ["talents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_talent_interactions_talent_id_occurred_on",
        "talent_interactions",
        ["talent_id", "occurred_on"],
    )
    op.create_index("ix_talent_interactions_next_due_on", "talent_interactions", ["next_due_on"])
    op.execute("ALTER TABLE talent_interactions ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_talent_interactions_next_due_on", table_name="talent_interactions")
    op.drop_index("ix_talent_interactions_talent_id_occurred_on", table_name="talent_interactions")
    op.drop_table("talent_interactions")
    op.drop_index("ix_talents_status", table_name="talents")
    op.drop_table("talents")
