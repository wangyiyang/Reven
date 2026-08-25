"""merge CRM and integration migration heads

Revision ID: 0014_merge_crm_and_integration
Revises: 0013_crm, 0013_integration_last_latency_ms
"""

revision = "0014_merge_crm_and_integration"
down_revision = ("0013_crm", "0013_integration_last_latency_ms")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
