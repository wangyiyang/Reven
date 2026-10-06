"""跟进/互动方式枚举两域合并：统一为 电话/面谈/微信/邮件/其他（#201 P3）

CRM `crm_follow_ups.kind` 的「会议」并入「面谈」，talents `talent_interactions.channel`
的「电话语音」并入「电话」并补「其他」：drop 旧 check 约束、按新集合重建同名约束。

本迁移假设两表无旧值（会议/电话语音）存量数据，不做数据 UPDATE；若目标库存在旧值行，
ADD CONSTRAINT 会失败，需先手工改写或删除这些行。downgrade 恢复旧字面量集合，同样
假设无新值（面谈@crm / 电话,其他@talents）存量。

Revision ID: 0027_unify_follow_up_channel
Revises: 0026_talent_profile
"""

from alembic import op

revision = "0027_unify_follow_up_channel"
down_revision = "0026_talent_profile"
branch_labels = None
depends_on = None

_CRM_KINDS_NEW = "kind IN ('电话', '面谈', '微信', '邮件', '其他')"
_CRM_KINDS_OLD = "kind IN ('电话', '会议', '微信', '邮件', '其他')"
_TALENT_CHANNELS_NEW = "channel IN ('电话', '面谈', '微信', '邮件', '其他')"
_TALENT_CHANNELS_OLD = "channel IN ('面谈', '电话语音', '微信', '邮件')"


def upgrade() -> None:
    op.drop_constraint("ck_crm_follow_ups_kind", "crm_follow_ups", type_="check")
    op.create_check_constraint("ck_crm_follow_ups_kind", "crm_follow_ups", _CRM_KINDS_NEW)
    op.drop_constraint("ck_talent_interactions_channel", "talent_interactions", type_="check")
    op.create_check_constraint("ck_talent_interactions_channel", "talent_interactions", _TALENT_CHANNELS_NEW)


def downgrade() -> None:
    op.drop_constraint("ck_crm_follow_ups_kind", "crm_follow_ups", type_="check")
    op.create_check_constraint("ck_crm_follow_ups_kind", "crm_follow_ups", _CRM_KINDS_OLD)
    op.drop_constraint("ck_talent_interactions_channel", "talent_interactions", type_="check")
    op.create_check_constraint("ck_talent_interactions_channel", "talent_interactions", _TALENT_CHANNELS_OLD)
