"""Contract obligations (feature expansion Phase 2): what a signed contract
commits the parties to after signature — SLA and service credits, licence
limits, price caps, audit rights, warranties, minimum commitments, exit
terms, data protection, liability and insurance.

  contract_obligations  one row per obligation; extracted ones start as
                        'to_confirm' until a person confirms them
  obligation_events     everything that happened to an obligation
  sla_credits           a service credit owed after recorded downtime,
                        expected on the vendor's next invoice

Additive: new tables and one nullable column on contracts.
"""
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

TYPES = ("sla_uptime", "license_limit", "price_cap", "audit_rights", "warranty", "termination_convenience",
         "minimum_commitment", "post_termination", "data_protection", "liability_cap", "insurance")


def upgrade():
    types = ", ".join(f"'{t}'" for t in TYPES)
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS contract_obligations (
            id UUID PRIMARY KEY,
            contract_id UUID NOT NULL REFERENCES contracts(id),
            type TEXT NOT NULL CHECK (type IN ({types})),
            clause_text TEXT,
            value JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            status TEXT NOT NULL DEFAULT 'to_confirm'
                CHECK (status IN ('to_confirm', 'open', 'met', 'breached', 'waived')),
            due_date DATE,
            recurrence TEXT NOT NULL DEFAULT 'none' CHECK (recurrence IN ('none', 'monthly', 'annual')),
            owner_email TEXT,
            license_id UUID,
            extracted_by TEXT NOT NULL CHECK (extracted_by IN ('legal-bert-cuad', 'regex', 'manual')),
            confidence NUMERIC,
            confirmed_by TEXT,
            confirmed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""")
    op.execute("CREATE INDEX IF NOT EXISTS idx_obligations_contract ON contract_obligations (contract_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_obligations_due ON contract_obligations (status, due_date)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_obligations_license ON contract_obligations (license_id) "
               "WHERE license_id IS NOT NULL")
    op.execute("""
        CREATE TABLE IF NOT EXISTS obligation_events (
            id UUID PRIMARY KEY,
            obligation_id UUID NOT NULL REFERENCES contract_obligations(id),
            kind TEXT NOT NULL CHECK (kind IN ('extracted', 'confirmed', 'edited', 'met', 'breach', 'back_within',
                                               'waived', 'reopened', 'downtime_recorded', 'reminder_sent')),
            details JSONB NOT NULL DEFAULT '{}'::jsonb,
            performed_by TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""")
    op.execute("CREATE INDEX IF NOT EXISTS idx_obligation_events ON obligation_events (obligation_id, created_at)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS sla_credits (
            id UUID PRIMARY KEY,
            obligation_id UUID NOT NULL REFERENCES contract_obligations(id),
            contract_id UUID NOT NULL REFERENCES contracts(id),
            purchase_request_id UUID,
            period TEXT NOT NULL,                      -- YYYY-MM
            measured_uptime_pct NUMERIC NOT NULL,
            credit_pct NUMERIC NOT NULL,
            credit_amount NUMERIC(14, 2) NOT NULL,
            currency TEXT NOT NULL DEFAULT 'INR',
            status TEXT NOT NULL DEFAULT 'expected' CHECK (status IN ('proposed', 'expected', 'applied', 'waived')),
            recorded_by TEXT NOT NULL,
            resolved_by TEXT,
            resolved_at TIMESTAMPTZ,
            note TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (obligation_id, period)
        )""")
    op.execute("CREATE INDEX IF NOT EXISTS idx_sla_credits_request ON sla_credits (purchase_request_id, status)")
    op.execute("ALTER TABLE contracts ADD COLUMN IF NOT EXISTS obligations_extracted_at TIMESTAMPTZ")


def downgrade():
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS obligations_extracted_at")
    op.execute("DROP TABLE IF EXISTS sla_credits")
    op.execute("DROP TABLE IF EXISTS obligation_events")
    op.execute("DROP TABLE IF EXISTS contract_obligations")
