"""Integrity: foreign key for webhook events, allowed contract statuses,
indexes for contract/risk lookups. Existing data was checked first.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-26
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        DO $$ BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_processed_webhook_events_contract') THEN
            ALTER TABLE processed_webhook_events ADD CONSTRAINT fk_processed_webhook_events_contract
              FOREIGN KEY (contract_id) REFERENCES contracts(id);
          END IF;
          IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_contracts_status') THEN
            ALTER TABLE contracts ADD CONSTRAINT ck_contracts_status
              CHECK (status IN ('draft', 'pending_signature', 'signed', 'terminated', 'expired'));
          END IF;
        END $$
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_contracts_request ON contracts (purchase_request_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_risk_scores_vendor ON risk_scores (vendor_id, scored_at DESC)")


def downgrade():
    op.execute("ALTER TABLE processed_webhook_events DROP CONSTRAINT IF EXISTS fk_processed_webhook_events_contract")
    op.execute("ALTER TABLE contracts DROP CONSTRAINT IF EXISTS ck_contracts_status")
    op.execute("DROP INDEX IF EXISTS idx_contracts_request")
    op.execute("DROP INDEX IF EXISTS idx_risk_scores_vendor")
