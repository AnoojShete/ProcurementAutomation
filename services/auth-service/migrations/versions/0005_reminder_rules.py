"""Business rules for pending-action reminders (FR-03, reminder.due):
when approvers, signers, bank-detail verifiers and document reviewers are
reminded. Insert-only and idempotent; downgrade removes them."""
import json

from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

RULES = [
    ("approval.reminder_sla_percents", "approval", "Approval Reminder Points (% of SLA)",
     "Remind the approver when this much of the approval SLA has passed", "json", [50, 80], None, None),
    ("contract.signature_reminder_days", "risk_compliance", "Signature Reminder (days)",
     "Remind the signer when a contract has waited this many days for signature", "int", 3, 1, 60),
    ("vendor.bank_verification_reminder_hours", "vendor_verification", "Bank-Detail Verification Reminder (hours)",
     "Remind finance when a bank-detail change has waited this long for the second person", "int", 24, 1, 720),
    ("document.review_reminder_hours", "vendor_verification", "Document Review Reminder (hours)",
     "Remind reviewers when a document has waited this long in the review queue", "int", 24, 1, 720),
]


def upgrade():
    for key, cat, name, desc, vtype, value, lo, hi in RULES:
        op.execute(sa.text(
            "INSERT INTO business_rules (id, rule_key, category, display_name, description, value_type, "
            "current_value, default_value, min_value, max_value) VALUES (gen_random_uuid(), :k, :c, :n, :d, :t, "
            "CAST(:v AS JSONB), CAST(:v AS JSONB), :lo, :hi) ON CONFLICT (rule_key) DO NOTHING"
        ).bindparams(k=key, c=cat, n=name, d=desc, t=vtype, v=json.dumps(value), lo=lo, hi=hi))


def downgrade():
    keys = tuple(r[0] for r in RULES)
    op.execute(sa.text("DELETE FROM business_rule_history WHERE rule_key IN :k").bindparams(sa.bindparam("k", expanding=True, value=list(keys))))
    op.execute(sa.text("DELETE FROM business_rules WHERE rule_key IN :k").bindparams(sa.bindparam("k", expanding=True, value=list(keys))))
