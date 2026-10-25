"""Prompt 10: Signing mandates, contract auto-signing metadata, and inherent tier history.

Revision ID: 0013
Revises: 0012
"""
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade():
    # 1. Table signing_mandates
    op.execute("""
        CREATE TABLE IF NOT EXISTS signing_mandates (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id TEXT NOT NULL,
            role TEXT NOT NULL,
            scope TEXT NOT NULL DEFAULT 'bulk_approved_contracts',
            max_amount_per_contract NUMERIC(12, 2) NOT NULL,
            valid_from TIMESTAMPTZ NOT NULL,
            valid_until TIMESTAMPTZ NOT NULL,
            mandate_text_version TEXT NOT NULL,
            mandate_text_sha256 VARCHAR(64) NOT NULL,
            accepted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            accepted_ip TEXT,
            accepted_user_agent TEXT,
            revoked_at TIMESTAMPTZ,
            revoked_by TEXT,
            status TEXT NOT NULL DEFAULT 'active'
        );
        CREATE INDEX IF NOT EXISTS idx_signing_mandates_user_status ON signing_mandates (user_id, status);
    """)

    # 2. Add contract columns
    op.execute("ALTER TABLE contracts ADD COLUMN IF NOT EXISTS signature_method TEXT DEFAULT 'manual'")
    op.execute("ALTER TABLE contracts ADD COLUMN IF NOT EXISTS approval_channel TEXT")
    op.execute("ALTER TABLE contracts ADD COLUMN IF NOT EXISTS bulk_batch_id UUID")
    op.execute("ALTER TABLE contracts ADD COLUMN IF NOT EXISTS mandate_id UUID")

    # 3. Add inherent tier history
    op.execute("""
        CREATE TABLE IF NOT EXISTS vendor_inherent_tier_history (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            vendor_id UUID NOT NULL REFERENCES vendors(id) ON DELETE CASCADE,
            old_tier TEXT,
            new_tier TEXT NOT NULL,
            justification TEXT NOT NULL,
            changed_by TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS idx_inherent_tier_history_vendor ON vendor_inherent_tier_history (vendor_id);
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS vendor_inherent_tier_history")
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS signature_method")
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS approval_channel")
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS bulk_batch_id")
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS mandate_id")
    op.execute("DROP TABLE IF EXISTS signing_mandates")
