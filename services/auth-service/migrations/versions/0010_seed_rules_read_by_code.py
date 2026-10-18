"""FR-09: rules the services already read but that were never seeded, so
admins couldn't see or change them (the code always used its fallback).
Seeded with exactly those fallbacks, so behaviour doesn't change.
Insert-only, idempotent."""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

# (key, category, name, description, type, value, min, max)
RULES = [
    ("approval.email_action_enabled", "approval", "Approve From Email",
     "Allow approvers to approve or reject from a single-use email link", "bool", "true", None, None),
    ("approval.email_action_max_amount", "approval", "Email Approval Limit (INR)",
     "Requests above this amount must be decided in the app, not from email", "float", "50000", 0, None),
    ("approval.email_action_allowed_over_budget", "approval", "Email Approval Over Budget",
     "Allow email approval of requests that exceed the budget", "bool", "false", None, None),
    ("approval.email_action_allowed_high_risk_vendor", "approval", "Email Approval For High-Risk Vendors",
     "Allow email approval when the vendor's risk band is High", "bool", "false", None, None),
    ("approval.email_token_ttl_hours", "approval", "Email Link Lifetime (hours)",
     "How long an approval link in an email stays valid (never past the SLA deadline)", "int", "48", 1, 168),
    ("invoice.overbill_tolerance_pct", "budget", "Invoice Over-Billing Tolerance",
     "An invoice may exceed the order's remaining balance by this fraction before it is held", "float", "0.01", 0, 0.2),
    ("invoice.unit_price_tolerance_pct", "budget", "Invoice Unit-Price Tolerance",
     "An invoiced unit price may exceed the ordered price by this fraction before it is held", "float", "0.01", 0, 0.2),
    ("vendor.duplicate_invoice_number_fuzzy_threshold", "vendor_verification", "Duplicate Invoice Number Similarity",
     "Invoice numbers at least this similar (0-100) from one vendor count as possible duplicates", "int", "85", 50, 100),
    ("vendor.lookalike_min_similarity", "vendor_verification", "Look-Alike Vendor Similarity",
     "A new vendor this similar (0-100) to an existing one is flagged as a possible impostor", "int", "70", 50, 100),
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
