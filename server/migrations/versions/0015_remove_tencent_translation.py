"""remove Tencent translation integration credentials

Revision ID: 0015_remove_tencent_translation
Revises: 0014_merge_crm_and_integration
"""

from alembic import op

revision = "0015_remove_tencent_translation"
down_revision = "0014_merge_crm_and_integration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # This deliberately removes the ciphertext too. The retired provider's
    # credentials cannot be reconstructed safely during a downgrade.
    op.execute("DELETE FROM integrations WHERE provider = 'translate_tencent'")


def downgrade() -> None:
    # No-op: restoring an empty row would imply that deleted credentials were
    # recoverable and would leave the integration in an unusable state.
    pass
