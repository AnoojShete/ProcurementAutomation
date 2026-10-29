"""Phase 2 (VEND-1): the two limits the financial-statement score uses when a
vendor has no credit rating. Insert-only, idempotent.

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-29
"""
from alembic import op
import sqlalchemy as sa

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

RULES = [
    ("risk.financial_min_current_ratio", "risk", "Financial Statement: Min Current Ratio",
     "Audited statements pass the liquidity check when current assets divided by current liabilities is at least this",
     "float", "1.2", 0.5, 5),
    ("risk.financial_max_debt_to_equity", "risk", "Financial Statement: Max Debt to Equity",
     "Audited statements pass the leverage check when total borrowings divided by total equity is at most this",
     "float", "1.0", 0, 5),
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
