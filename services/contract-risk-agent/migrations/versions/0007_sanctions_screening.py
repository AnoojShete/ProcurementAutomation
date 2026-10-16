"""Sanctions screening results per vendor (FR-14). One row per screening;
a finance clearance is a new row with status 'cleared'. Additive."""
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS vendor_sanctions_screenings (
            id UUID PRIMARY KEY,
            vendor_id UUID NOT NULL REFERENCES vendors(id),
            screened_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            list_version TEXT,
            screened_name TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('clear', 'potential_match', 'cleared')),
            matches JSONB NOT NULL DEFAULT '[]'::jsonb,
            threshold NUMERIC,
            screened_by TEXT,
            justification TEXT
        )""")
    op.execute("CREATE INDEX IF NOT EXISTS idx_sanctions_vendor ON vendor_sanctions_screenings (vendor_id, screened_at DESC)")
    # Read by the risk model's IFSC hard check; written by document-vendor-agent
    # (which adds it too — IF NOT EXISTS keeps start-up order irrelevant).
    op.execute("ALTER TABLE vendors ADD COLUMN IF NOT EXISTS ifsc_verification_status TEXT")


def downgrade():
    op.execute("DROP TABLE IF EXISTS vendor_sanctions_screenings")
