"""Prompt 12B & 12C: Security events audit table, refresh token family rotation,
and user/vendor country attribution for privacy cross-border checks.

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-02
"""
from alembic import op
import sqlalchemy as sa

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade():
    # 1. security_events table (OWASP API Security Top 10 detection & response)
    op.execute("""
        CREATE TABLE IF NOT EXISTS security_events (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
            event_type VARCHAR(50) NOT NULL,
            user_id VARCHAR(64),
            ip_hash VARCHAR(64),
            route VARCHAR(255),
            detail JSONB NOT NULL DEFAULT '{}'::jsonb
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_security_events_type_time ON security_events (event_type, timestamp DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_security_events_user ON security_events (user_id, timestamp DESC)")

    # 2. auth_refresh_token_families (Refresh token rotation and reuse detection)
    op.execute("""
        CREATE TABLE IF NOT EXISTS auth_refresh_token_families (
            family_id UUID PRIMARY KEY,
            user_id UUID NOT NULL,
            last_token_jti VARCHAR(64) NOT NULL,
            is_revoked BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            revoked_at TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_refresh_families_user ON auth_refresh_token_families (user_id, is_revoked)")

    # 3. Country attribution for cross-border privacy checks
    op.execute("ALTER TABLE auth_users ADD COLUMN IF NOT EXISTS country VARCHAR(3)")
    op.execute("ALTER TABLE vendors ADD COLUMN IF NOT EXISTS contact_country VARCHAR(3)")
    op.execute("ALTER TABLE vendors ADD COLUMN IF NOT EXISTS legal_hold BOOLEAN DEFAULT false")
    op.execute("ALTER TABLE purchase_requests ADD COLUMN IF NOT EXISTS legal_hold BOOLEAN DEFAULT false")


def downgrade():
    op.execute("DROP TABLE IF EXISTS auth_refresh_token_families")
    op.execute("DROP TABLE IF EXISTS security_events")
    op.execute("ALTER TABLE auth_users DROP COLUMN IF EXISTS country")
    op.execute("ALTER TABLE vendors DROP COLUMN IF EXISTS contact_country")
    op.execute("ALTER TABLE vendors DROP COLUMN IF EXISTS legal_hold")
    op.execute("ALTER TABLE purchase_requests DROP COLUMN IF EXISTS legal_hold")
