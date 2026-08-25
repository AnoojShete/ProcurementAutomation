"""Extend shared schema for contract-risk-agent

Adds columns/tables this service needs on top of shared/db/init.sql,
without ever editing that file. Every statement is idempotent (IF NOT
EXISTS) so it's safe to run alongside migrations another service adds
later against the same shared tables.

Revision ID: 0001
Revises:
Create Date: 2026-08-25
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE vendors ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'active'")
    op.execute("ALTER TABLE vendors ADD COLUMN IF NOT EXISTS portal_access_revoked BOOLEAN DEFAULT false")
    op.execute("ALTER TABLE vendors ADD COLUMN IF NOT EXISTS data_retention_flag BOOLEAN DEFAULT false")
    op.execute("ALTER TABLE vendors ADD COLUMN IF NOT EXISTS offboarded_at TIMESTAMPTZ")
    op.execute("ALTER TABLE vendors ADD COLUMN IF NOT EXISTS offboarded_by VARCHAR(255)")

    op.execute("ALTER TABLE purchase_requests ADD COLUMN IF NOT EXISTS vendor_id UUID REFERENCES vendors(id)")
    op.execute("ALTER TABLE purchase_requests ADD COLUMN IF NOT EXISTS items JSONB")

    op.execute("ALTER TABLE contracts ADD COLUMN IF NOT EXISTS contract_text TEXT")
    op.execute("ALTER TABLE contracts ADD COLUMN IF NOT EXISTS renewal_type VARCHAR(20)")
    op.execute("ALTER TABLE contracts ADD COLUMN IF NOT EXISTS notice_period_days INTEGER")
    op.execute("ALTER TABLE contracts ADD COLUMN IF NOT EXISTS contract_end_date DATE")
    op.execute("ALTER TABLE contracts ADD COLUMN IF NOT EXISTS generated_at TIMESTAMPTZ")
    op.execute("ALTER TABLE contracts ADD COLUMN IF NOT EXISTS signed_at TIMESTAMPTZ")
    op.execute("ALTER TABLE contracts ADD COLUMN IF NOT EXISTS signed_by VARCHAR(255)")
    op.execute("ALTER TABLE contracts ADD COLUMN IF NOT EXISTS esign_provider_ref VARCHAR(255)")
    op.execute("ALTER TABLE contracts ADD COLUMN IF NOT EXISTS reconciliation_status VARCHAR(30)")
    op.execute("ALTER TABLE contracts ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ")

    op.execute("ALTER TABLE risk_scores ADD COLUMN IF NOT EXISTS model_version VARCHAR(50)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS vendor_risk_features (
          vendor_id UUID PRIMARY KEY REFERENCES vendors(id),
          vendor_tenure_months INTEGER,
          on_time_delivery_rate NUMERIC,
          financial_stability_score NUMERIC,
          breach_disclosure_count INTEGER,
          security_cert_flag BOOLEAN DEFAULT false,
          geo_risk_flag BOOLEAN DEFAULT false,
          updated_at TIMESTAMPTZ DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS risk_score_outcomes (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          vendor_id UUID REFERENCES vendors(id),
          risk_score_at_time NUMERIC,
          risk_band_at_time TEXT,
          actual_incident_occurred BOOLEAN,
          notes TEXT,
          logged_by TEXT,
          logged_at TIMESTAMPTZ DEFAULT now()
        )
        """
    )


def downgrade():
    op.execute("DROP TABLE IF EXISTS risk_score_outcomes")
    op.execute("DROP TABLE IF EXISTS vendor_risk_features")
    op.execute("ALTER TABLE risk_scores DROP COLUMN IF EXISTS model_version")
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS updated_at")
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS reconciliation_status")
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS esign_provider_ref")
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS signed_by")
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS signed_at")
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS generated_at")
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS contract_end_date")
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS notice_period_days")
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS renewal_type")
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS contract_text")
    op.execute("ALTER TABLE purchase_requests DROP COLUMN IF EXISTS items")
    op.execute("ALTER TABLE purchase_requests DROP COLUMN IF EXISTS vendor_id")
    op.execute("ALTER TABLE vendors DROP COLUMN IF EXISTS offboarded_by")
    op.execute("ALTER TABLE vendors DROP COLUMN IF EXISTS offboarded_at")
    op.execute("ALTER TABLE vendors DROP COLUMN IF EXISTS data_retention_flag")
    op.execute("ALTER TABLE vendors DROP COLUMN IF EXISTS portal_access_revoked")
    op.execute("ALTER TABLE vendors DROP COLUMN IF EXISTS status")
