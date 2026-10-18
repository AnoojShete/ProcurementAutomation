"""Add model routing log

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-25
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

def upgrade():
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS model_routing_log (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            document_id UUID,
            route_name VARCHAR(50) NOT NULL,
            model_used VARCHAR(50) NOT NULL,
            fallback_triggered BOOLEAN DEFAULT false,
            fallback_reason VARCHAR(50),
            confidence NUMERIC(4,3),
            duration_ms NUMERIC(10,2),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

def downgrade():
    op.execute("DROP TABLE IF EXISTS model_routing_log")
