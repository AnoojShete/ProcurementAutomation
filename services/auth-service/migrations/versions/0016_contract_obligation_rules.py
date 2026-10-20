"""Feature expansion Phase 2: contract obligations (contract-risk-agent's
obligation_service.py). Insert-only, idempotent.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-20
"""
from alembic import op
import sqlalchemy as sa

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

# (key, category, name, description, type, value, min, max)
RULES = [
    ("contract.obligation_reminder_days", "risk_compliance", "Obligation Reminder Days",
     "Days before a confirmed obligation's due date (warranty end, audit window, price-cap review …) "
     "when its owner is reminded", "json", "[30, 7]", None, None),
    ("contract.obligation_model_min_confidence", "risk_compliance", "Obligation Model Minimum Score",
     "Legal-BERT passages scoring below this (answer score minus no-answer score) are not proposed as obligations",
     "float", "0.5", 0, 20),
    ("contract.sla_credit_auto_expect", "risk_compliance", "Expect SLA Credits Automatically",
     "A service credit computed from recorded downtime is expected on the next invoice straight away; "
     "when off, finance accepts each credit first", "bool", "true", None, None),
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
