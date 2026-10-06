"""Talent 画像扩展：talents 加联系方式与 preferences，新建履历/院校子表（#201 P2）

talents 新增 phone / email / wechat（可空，长度对齐 CRM Contact）与
preferences（JSONB 数组，默认空，与 tags 并列：tags=能力/行业，preferences=喜好/个人）；
新建 1—N 子表 talent_experiences（工作履历）与 talent_educations（毕业院校），
FK ON DELETE CASCADE，end_on IS NULL 表示「至今」并带区间 check 约束，
复合索引 (talent_id, start_on)，沿用 ENABLE ROW LEVEL SECURITY 惯例。

Revision ID: 0026_talent_profile
Revises: 0025_crm_plan_derive
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0026_talent_profile"
down_revision = "0025_crm_plan_derive"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _extend_talents()
    _create_talent_experiences()
    _create_talent_educations()


def _extend_talents() -> None:
    op.add_column("talents", sa.Column("phone", sa.String(length=50), nullable=True))
    op.add_column("talents", sa.Column("email", sa.String(length=320), nullable=True))
    op.add_column("talents", sa.Column("wechat", sa.String(length=100), nullable=True))
    op.add_column(
        "talents",
        sa.Column(
            "preferences",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_talents_preferences_array",
        "talents",
        "jsonb_typeof(preferences) = 'array'",
    )


def _create_talent_experiences() -> None:
    op.create_table(
        "talent_experiences",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("talent_id", sa.Uuid(), nullable=False),
        sa.Column("company", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("start_on", sa.Date(), nullable=False),
        sa.Column("end_on", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "end_on IS NULL OR end_on >= start_on",
            name="ck_talent_experiences_date_range",
        ),
        sa.ForeignKeyConstraint(["talent_id"], ["talents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_talent_experiences_talent_id_start_on",
        "talent_experiences",
        ["talent_id", "start_on"],
    )
    op.execute("ALTER TABLE talent_experiences ENABLE ROW LEVEL SECURITY")


def _create_talent_educations() -> None:
    op.create_table(
        "talent_educations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("talent_id", sa.Uuid(), nullable=False),
        sa.Column("school", sa.Text(), nullable=False),
        sa.Column("degree", sa.Text(), nullable=True),
        sa.Column("major", sa.Text(), nullable=True),
        sa.Column("start_on", sa.Date(), nullable=False),
        sa.Column("end_on", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "end_on IS NULL OR end_on >= start_on",
            name="ck_talent_educations_date_range",
        ),
        sa.ForeignKeyConstraint(["talent_id"], ["talents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_talent_educations_talent_id_start_on",
        "talent_educations",
        ["talent_id", "start_on"],
    )
    op.execute("ALTER TABLE talent_educations ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_talent_educations_talent_id_start_on", table_name="talent_educations")
    op.drop_table("talent_educations")
    op.drop_index("ix_talent_experiences_talent_id_start_on", table_name="talent_experiences")
    op.drop_table("talent_experiences")
    op.drop_constraint("ck_talents_preferences_array", "talents", type_="check")
    op.drop_column("talents", "preferences")
    op.drop_column("talents", "wechat")
    op.drop_column("talents", "email")
    op.drop_column("talents", "phone")
