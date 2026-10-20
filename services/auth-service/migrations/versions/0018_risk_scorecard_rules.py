"""Rules the deterministic vendor risk scorecard (contract-risk-agent,
merged from updated_risk) reads but had no seed for, so admins could not
change them and tests/test_business_rules_registry.py failed. Defaults are
the code's own fallbacks, except risk.alert_recipients, which keeps the
address High-risk alerts went to before the scorecard (otherwise they would
silently stop). Insert-only, idempotent.

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-21
"""
from alembic import op
import sqlalchemy as sa

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

# (key, category, name, description, type, value, min, max)
RULES = [
    ("risk.petty_threshold", "risk_compliance", "Petty Purchase Clearance Limit",
     "A provisional (not fully assessed) low-tier vendor is still cleared for a purchase or contract up to this amount, "
     "if no hard override fired", "float", "50000", 0, 10000000),
    ("risk.alert_recipients", "risk_compliance", "High-Risk Alert Recipients",
     "E-mail address notified when a vendor turns High risk or a new hard override fires (empty = no e-mail)",
     "json", '"procurement-risk-team@company.com"', None, None),
    ("risk.min_relationship_days", "risk_compliance", "Minimum Relationship for Incident History",
     "Days a vendor must be on file (if it has no delivered order yet) before its incident history counts as assessed",
     "int", "90", 0, 3650),
    ("risk.raw_retention_months", "risk_compliance", "Raw Signal Retention (months)",
     "How long raw responses from the risk signal collectors are kept", "int", "24", 1, 120),
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
