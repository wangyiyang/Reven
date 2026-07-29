"""unify all notification events in the independent outbox

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.rename_table("preparation_notification_outbox", "notification_outbox")
    op.drop_index("ix_preparation_notification_due", table_name="notification_outbox")
    op.add_column(
        "notification_outbox",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_notification_outbox_due",
        "notification_outbox",
        ["status", "next_attempt_at"],
    )
    _migrate_legacy_events()
    _clear_completed_finalization()


def downgrade() -> None:
    op.drop_index("ix_notification_outbox_due", table_name="notification_outbox")
    op.drop_column("notification_outbox", "created_at")
    op.rename_table("notification_outbox", "preparation_notification_outbox")
    op.create_index(
        "ix_preparation_notification_due",
        "preparation_notification_outbox",
        ["status", "next_attempt_at"],
    )
    # 已转换的交付事件保留在旧 0003 Outbox 中，避免降级时丢失待发送通知。
    # 已清除的纯终态 finalization 不恢复；它不再承载未完成工作。


def _migrate_legacy_events() -> None:
    op.execute(
        """
            INSERT INTO notification_outbox (
                id, fingerprint, job_id, article_id, event, payload, revision,
                status, attempts, next_attempt_at, lease_token,
                lease_expires_at, last_error, sent_at, created_at
            )
            SELECT
                (
                    substr(md5(job.id::text || ':' || item.ordinality::text), 1, 8) || '-' ||
                    substr(md5(job.id::text || ':' || item.ordinality::text), 9, 4) || '-' ||
                    substr(md5(job.id::text || ':' || item.ordinality::text), 13, 4) || '-' ||
                    substr(md5(job.id::text || ':' || item.ordinality::text), 17, 4) || '-' ||
                    substr(md5(job.id::text || ':' || item.ordinality::text), 21, 12)
                )::uuid,
                item.value->>'fingerprint',
                job.id,
                job.article_id,
                item.value->>'event',
                jsonb_build_object(
                    'title', article.title,
                    'stage', coalesce(item.value->>'stage', ''),
                    'summary', coalesce(item.value->>'summary', ''),
                    'links', jsonb_build_object('Notion', article.notion_url),
                    'error_code', item.value->'error_code',
                    'channel', item.value->'channel'
                ),
                coalesce(
                    (regexp_match(item.value->>'event', '\\:r([0-9]+)$'))[1]::integer,
                    item.ordinality::integer
                ),
                'pending',
                0,
                clock_timestamp() + item.ordinality * interval '1 microsecond',
                NULL,
                NULL,
                NULL,
                NULL,
                clock_timestamp() + item.ordinality * interval '1 microsecond'
            FROM publication_jobs AS job
            JOIN articles AS article ON article.id = job.article_id
            CROSS JOIN LATERAL jsonb_array_elements(
                CASE
                    WHEN jsonb_typeof(job.snapshot_metadata->'delivery_notification_events') = 'array'
                    THEN job.snapshot_metadata->'delivery_notification_events'
                    ELSE '[]'::jsonb
                END
            ) WITH ORDINALITY AS item(value, ordinality)
            WHERE item.value->>'fingerprint' ~ '^[0-9a-f]{64}$'
              AND nullif(item.value->>'event', '') IS NOT NULL
            ON CONFLICT (fingerprint) DO NOTHING
            """
    )
    # 无 fingerprint 或 event 的旧事件无法安全去重，显式不迁移；随后统一删除旧 key。
    op.execute(
        """
        UPDATE publication_jobs
        SET snapshot_metadata = snapshot_metadata - 'delivery_notification_events'
        WHERE snapshot_metadata ? 'delivery_notification_events'
        """
    )


def _clear_completed_finalization() -> None:
    op.execute(
        """
        UPDATE publication_jobs
        SET snapshot_metadata = snapshot_metadata - 'delivery_finalization'
        WHERE snapshot_metadata ? 'delivery_finalization'
          AND snapshot_metadata->'delivery_finalization'->'notion_pending' = 'false'::jsonb
          AND snapshot_metadata->'delivery_finalization'->'cleanup_pending' = 'false'::jsonb
        """
    )
