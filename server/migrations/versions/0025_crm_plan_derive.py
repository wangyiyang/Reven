"""CRM 计划派生化：删除客户表双写计划字段，跟进表 next_follow_up_on 改名 next_due_on（#201 P1）

客户的「当前计划」改为从最新一条跟进记录派生，crm_customers 不再持有
next_action / next_follow_up_on 双写列及其配对 check 约束（索引随列删除）；
crm_follow_ups.next_follow_up_on 更名为 next_due_on（PG 自动更新配对 check 约束
ck_crm_follow_ups_follow_up_action 的列引用，约束保留）。

Revision ID: 0025_crm_plan_derive
Revises: 0024_rss_resilience
"""

import sqlalchemy as sa
from alembic import op

revision = "0025_crm_plan_derive"
down_revision = "0024_rss_resilience"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_crm_customers_follow_up_action", "crm_customers", type_="check")
    op.drop_column("crm_customers", "next_action")
    op.drop_column("crm_customers", "next_follow_up_on")
    op.alter_column("crm_follow_ups", "next_follow_up_on", new_column_name="next_due_on")


def downgrade() -> None:
    op.alter_column("crm_follow_ups", "next_due_on", new_column_name="next_follow_up_on")
    op.add_column("crm_customers", sa.Column("next_action", sa.Text(), nullable=True))
    op.add_column("crm_customers", sa.Column("next_follow_up_on", sa.Date(), nullable=True))
    op.create_index("ix_crm_customers_next_follow_up_on", "crm_customers", ["next_follow_up_on"])
    op.create_check_constraint(
        "ck_crm_customers_follow_up_action",
        "crm_customers",
        "next_follow_up_on IS NULL OR (next_action IS NOT NULL AND btrim(next_action) <> '')",
    )
