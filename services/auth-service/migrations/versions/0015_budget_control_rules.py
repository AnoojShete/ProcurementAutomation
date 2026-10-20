"""Feature expansion Phase 1: budget control before approval.

The two budget rules seeded in 0002 (budget.fiscal_period_type,
budget.over_budget_requires_finance_approval) become enforced by
approval-inventory-agent's budget_service; these five complete them.

Defaults change nothing for existing data: there are no budgets yet, a
request without one is allowed (no_budget_policy = allow), nothing is
blocked, and the vendor-risk routing rule is off until an admin turns it on.
Insert-only, idempotent.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-20
"""
from alembic import op
import sqlalchemy as sa

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

# (key, category, name, description, type, value, min, max)
RULES = [
    ("budget.fiscal_year_start_month", "budget", "Fiscal Year Start Month",
     "Month the fiscal year starts (4 = April, the Indian fiscal year); sets which quarter a request falls in",
     "int", "4", 1, 12),
    ("budget.warning_threshold_pct", "budget", "Budget Warning Threshold",
     "A request that takes its budget past this share of the amount is marked as a warning and notified",
     "float", "0.8", 0.1, 1),
    ("budget.block_when_over", "budget", "Refuse Over-Budget Requests",
     "Refuse a request that would exceed its budget instead of sending it for finance approval",
     "bool", "false", None, None),
    ("budget.no_budget_policy", "budget", "Requests Without A Budget",
     "What happens to a request when its department has no budget for the category and period: "
     "'allow', 'finance_approval' or 'block'",
     "json", '"allow"', None, None),
    ("approval.high_risk_vendor_requires_finance", "approval", "High-Risk Vendor Needs Finance",
     "Add a finance approval step to purchases from vendors whose risk band is High",
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
