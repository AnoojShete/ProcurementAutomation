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


def downgrade():
    op.execute("DROP TABLE IF EXISTS processed_webhook_events")
