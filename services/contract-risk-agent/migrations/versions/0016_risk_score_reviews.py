"""AI second opinion on a risk score: what the review model flagged.

One row per review of a score (app/services/risk_review.py). Flags are
shown to the buyer; nothing here feeds back into the score or clearance.

Revision ID: 0016
Revises: 0015
"""
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS risk_score_reviews (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            score_id UUID NOT NULL REFERENCES risk_scores(id) ON DELETE CASCADE,
            vendor_id UUID NOT NULL,
            model TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('ok', 'unavailable')),
            flags JSONB NOT NULL DEFAULT '[]'::jsonb,
            requested_by TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_risk_score_reviews_vendor ON risk_score_reviews (vendor_id, created_at DESC)")


def downgrade():
    op.execute("DROP TABLE IF EXISTS risk_score_reviews")
