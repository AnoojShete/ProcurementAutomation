"""FR-04 / merge review G2: whether a purchase from a vendor whose risk
checks are incomplete (Unrated) gets a finance step, as a High-risk vendor's
can (approval.high_risk_vendor_requires_finance). Off by default: in a stack
without external data sources almost every vendor is Unrated, and turning
this on routes all their purchases to finance. Insert-only, idempotent.

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-21
"""
from alembic import op
import sqlalchemy as sa

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

RULES = [
    ("approval.unrated_vendor_requires_finance", "approval", "Unrated Vendor Requires Finance",
     "Purchases from a vendor whose risk checks are incomplete (Unrated) get a finance approval step",
     "bool", "false", None, None),
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
