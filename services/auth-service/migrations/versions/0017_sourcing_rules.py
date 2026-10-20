"""Feature expansion Phase 3: IT catalog, RFQs, partial goods receipts
(approval-inventory-agent's catalog_service.py, sourcing_service.py,
invoice_ledger.py). Insert-only, idempotent.

Defaults change no existing flow: catalog pre-approval is off (0), the RFQ
threshold only adds an advisory note, and receipt matching only applies to
requests that have goods receipts (there are none before Phase 3).

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-20
"""
from alembic import op
import sqlalchemy as sa

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

CRITERIA = ('{"price": 0.45, "lead_time": 0.15, "warranty": 0.1, "support": 0.1, '
            '"vendor_risk": 0.1, "delivery_record": 0.1}')

# (key, category, name, description, type, value, min, max)
RULES = [
    ("catalog.preapproved_max_inr", "approval", "Pre-approved Catalog Amount",
     "Requests made only of catalog items, up to this amount, skip the manager step (0 = off); "
     "finance steps from the budget or vendor-risk rules stay", "float", "0", 0, 10000000),
    ("sourcing.rfq_required_above_inr", "approval", "RFQ Recommended Above",
     "A request above this amount with no RFQ or catalog price is flagged on its page (advisory; 0 = off)",
     "float", "200000", 0, 100000000),
    ("sourcing.default_criteria", "approval", "RFQ Scoring Weights",
     "Weights for comparing RFQ quotes: price, lead_time, warranty, support, vendor_risk, delivery_record "
     "(they add up to 1); each new RFQ starts with these", "json", CRITERIA, None, None),
    ("invoice.match_against_received", "budget", "Match Invoices Against Received Goods",
     "Once goods receipts exist for a request, an invoice line for more than has been received is a variance "
     "(three-way match)", "bool", "true", None, None),
]


def upgrade():
    for key, category, name, description, vtype, value, lo, hi in RULES:
        op.execute(sa.text(
            "INSERT INTO business_rules (id, rule_key, category, display_name, description, value_type, "
            "current_value, default_value, min_value, max_value) VALUES (gen_random_uuid(), "
            ":key, :category, :name, :description, :vtype, CAST(:value AS jsonb), CAST(:value AS jsonb), :lo, :hi) "
            "ON CONFLICT (rule_key) DO NOTHING"
        ).bindparams(key=key, category=category, name=name, description=description, vtype=vtype,
                     value=value, lo=lo, hi=hi))


def downgrade():
    for key, *_ in RULES:
        op.execute(sa.text("DELETE FROM business_rule_history WHERE rule_key = :key").bindparams(key=key))
        op.execute(sa.text("DELETE FROM business_rules WHERE rule_key = :key").bindparams(key=key))
