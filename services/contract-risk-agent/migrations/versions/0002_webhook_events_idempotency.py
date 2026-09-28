"""Add processed_webhook_events (e-sign webhook replay protection)

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-25
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS processed_webhook_events (
          provider_event_id VARCHAR(255) PRIMARY KEY,
          contract_id UUID,
          processed_at TIMESTAMPTZ DEFAULT now()
        )
        """
    )
    # shared/db/init.sql may have created the earlier generic shape first.
    op.execute("ALTER TABLE processed_webhook_events ADD COLUMN IF NOT EXISTS provider_event_id VARCHAR(255)")
    op.execute("ALTER TABLE processed_webhook_events ADD COLUMN IF NOT EXISTS contract_id UUID")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_processed_webhook_provider_event_id ON processed_webhook_events(provider_event_id)")


def downgrade():
    op.execute("DROP TABLE IF EXISTS processed_webhook_events")
