"""Prompt 10: Seed business rules for bulk approval, finance auto-signing mandates,
reorder request roles, and petty vendor threshold.
Insert-only, idempotent.

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-24
"""
from alembic import op
import sqlalchemy as sa

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

RULES = [
    # Bulk Approval (Section 1.1)
    ("approval.bulk_approve_enabled", "approval", "Bulk Approval Enabled",
     "Allow approvers and finance users to approve multiple eligible requests at once in the application",
     "bool", "true", None, None),
    ("approval.bulk_approve_max_amount", "approval", "Bulk Approval Max Amount (INR)",
     "Maximum request amount eligible for bulk approval. Requests above this limit must be approved one by one.",
     "float", "25000", 0, None),
    ("approval.bulk_approve_max_items", "approval", "Bulk Approval Max Items Per Batch",
     "Maximum number of requests that can be approved in a single bulk batch",
     "int", "25", 1, 100),
    ("approval.bulk_approve_max_batch_total", "approval", "Bulk Approval Max Batch Total (INR)",
     "Maximum cumulative amount that can be approved across all items in a single bulk batch",
     "float", "250000", 0, None),
    ("approval.bulk_email_enabled", "approval", "Bulk Email Digest Approval Enabled",
     "Allow approvers to review and approve batches of eligible requests from an email digest",
     "bool", "true", None, None),
    ("approval.bulk_email_token_ttl_hours", "approval", "Bulk Email Token Lifetime (hours)",
     "How long an email bulk approval batch token remains valid",
     "int", "48", 1, 168),
    ("approval.bulk_actions_per_hour", "approval", "Bulk Approval Actions Per Hour",
     "Rate limit on bulk approval actions per approver per hour",
     "int", "20", 1, 1000),
    ("approval.bulk_excluded_request_types", "approval", "Bulk Approval Excluded Request Types",
     "List of request types excluded from bulk approval (e.g. ['reclaim'])",
     "json", "[]", None, None),
    ("approval.bulk_digest_enabled", "approval", "Bulk Approval Daily Digest Enabled",
     "Send daily email digest of pending eligible requests to approvers",
     "bool", "true", None, None),
    ("approval.bulk_digest_time_ist", "approval", "Bulk Approval Digest Time (IST)",
     "Time of day (IST 24h format HH:MM) when daily digest is sent",
     "string", '"09:00"', None, None),
    ("approval.bulk_digest_min_items", "approval", "Bulk Approval Digest Min Items",
     "Minimum number of eligible pending requests required to trigger a digest email",
     "int", "2", 1, 100),

    # Contract Auto-Sign Under Mandate (Section 2.1)
    ("contract.auto_sign_enabled", "contract", "Finance Auto-Signing Enabled",
     "Automatically sign generated contracts for bulk approved requests when an active mandate exists",
     "bool", "false", None, None),
    ("contract.auto_sign_max_amount", "contract", "Contract Auto-Sign Max Amount (INR)",
     "Upper spend limit for automatic contract signing under a mandate",
     "float", "25000", 0, None),
    ("contract.auto_sign_allow_email_channel", "contract", "Allow Auto-Sign From Email Bulk Approval",
     "Allow auto-signing when bulk approval was submitted via an email digest link",
     "bool", "true", None, None),
    ("contract.mandate_max_days", "contract", "Signing Mandate Max Validity (days)",
     "Maximum duration a finance signing mandate can remain valid before requiring renewal",
     "int", "90", 1, 365),
    ("contract.auto_sign_roles", "contract", "Roles Permitted to Hold Signing Mandate",
     "User roles permitted to create and hold an automatic signing mandate",
     "json", '["finance"]', None, None),

    # Petty Vendor Limit (Section 6.2)
    ("vendor.petty_tier_max_amount", "vendor", "Petty Vendor Tier Max Amount (INR)",
     "Maximum spend threshold for a vendor in the petty tier without full assessment checks",
     "float", "5000", 0, None),

    # Reorder Request Creation Roles (Section 4.4)
    ("reorder.create_request_roles", "inventory", "Roles Allowed to Create Request from Reorder",
     "Roles allowed to create a purchase request directly from an inventory reorder suggestion",
     "json", '["requester", "approver", "finance", "admin"]', None, None),
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
