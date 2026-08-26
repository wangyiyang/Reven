"""merge talents and remove Tencent translation migration heads

Revision ID: 0016_merge_talents_tencent
Revises: 0015_talents, 0015_remove_tencent_translation
"""

revision = "0016_merge_talents_tencent"
down_revision = ("0015_talents", "0015_remove_tencent_translation")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
