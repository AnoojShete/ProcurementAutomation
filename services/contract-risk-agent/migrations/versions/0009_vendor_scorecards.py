"""Vendor scorecards (feature expansion Phase 3c): one row per vendor,
recomputed nightly and on demand from data the platform already has —
deliveries, invoice matches, RFQ invitations, SLA breaches, risk band.
RFQ scoring (approval-inventory-agent) reads the on-time rate from here.

Additive: one new table.
"""
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS vendor_scorecards (
            vendor_id UUID PRIMARY KEY REFERENCES vendors(id),
            on_time_rate NUMERIC,
            deliveries INTEGER NOT NULL DEFAULT 0,
            invoice_accuracy NUMERIC,
            invoices INTEGER NOT NULL DEFAULT 0,
            rfq_response_rate NUMERIC,
            rfq_invitations INTEGER NOT NULL DEFAULT 0,
            sla_breaches INTEGER NOT NULL DEFAULT 0,
            risk_band TEXT,
            computed_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""")


def downgrade():
    op.execute("DROP TABLE IF EXISTS vendor_scorecards")
