"""add CRM customers, contacts, and follow-ups

Revision ID: 0013_crm
Revises: 0012_playbooks
"""

import sqlalchemy as sa
from alembic import op

revision = "0013_crm"
down_revision = "0012_playbooks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _create_customers()
    _create_contacts()
    _create_follow_ups()


def _create_customers() -> None:
    op.create_table(
        "crm_customers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("next_action", sa.Text(), nullable=True),
        sa.Column("next_follow_up_on", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('潜在客户', '跟进中', '合作客户', '暂停跟进', '已流失')",
            name="ck_crm_customers_status",
        ),
        sa.CheckConstraint(
            "next_follow_up_on IS NULL OR (next_action IS NOT NULL AND btrim(next_action) <> '')",
            name="ck_crm_customers_follow_up_action",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_crm_customers_status", "crm_customers", ["status"])
    op.create_index("ix_crm_customers_next_follow_up_on", "crm_customers", ["next_follow_up_on"])
    op.execute("ALTER TABLE crm_customers ENABLE ROW LEVEL SECURITY")


def _create_contacts() -> None:
    op.create_table(
        "crm_contacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("role", sa.String(length=100), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("wechat", sa.String(length=100), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["crm_customers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_crm_contacts_customer_id", "crm_contacts", ["customer_id"])
    op.create_index(
        "uq_crm_contacts_primary_per_customer",
        "crm_contacts",
        ["customer_id"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
    )
    op.execute("ALTER TABLE crm_contacts ENABLE ROW LEVEL SECURITY")


def _create_follow_ups() -> None:
    op.create_table(
        "crm_follow_ups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=True),
        sa.Column("contact_name_snapshot", sa.String(length=200), nullable=True),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("next_action", sa.Text(), nullable=True),
        sa.Column("next_follow_up_on", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('电话', '会议', '微信', '邮件', '其他')",
            name="ck_crm_follow_ups_kind",
        ),
        sa.CheckConstraint(
            "next_follow_up_on IS NULL OR (next_action IS NOT NULL AND btrim(next_action) <> '')",
            name="ck_crm_follow_ups_follow_up_action",
        ),
        sa.ForeignKeyConstraint(["contact_id"], ["crm_contacts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["customer_id"], ["crm_customers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_crm_follow_ups_customer_id", "crm_follow_ups", ["customer_id"])
    op.create_index("ix_crm_follow_ups_occurred_on", "crm_follow_ups", ["occurred_on"])
    op.execute("ALTER TABLE crm_follow_ups ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_crm_follow_ups_occurred_on", table_name="crm_follow_ups")
    op.drop_index("ix_crm_follow_ups_customer_id", table_name="crm_follow_ups")
    op.drop_table("crm_follow_ups")
    op.drop_index("uq_crm_contacts_primary_per_customer", table_name="crm_contacts")
    op.drop_index("ix_crm_contacts_customer_id", table_name="crm_contacts")
    op.drop_table("crm_contacts")
    op.drop_index("ix_crm_customers_next_follow_up_on", table_name="crm_customers")
    op.drop_index("ix_crm_customers_status", table_name="crm_customers")
    op.drop_table("crm_customers")
