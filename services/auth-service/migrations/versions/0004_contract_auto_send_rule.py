"""Business rule contract.auto_send_scope: which approved requests get
their contract sent for signature automatically — "all" (default) or only
"drop_folder" (quotes dropped in ./inbox, the behaviour before Oct 16).

Insert-only and idempotent (ON CONFLICT DO NOTHING); downgrade removes the
rule and its history rows.
"""
import json

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

RULE = {
    "rule_key": "contract.auto_send_scope",
    "category": "risk_compliance",
    "display_name": "Contract Auto-Send Scope",
    "description": (
        "Which approved requests get their contract sent for signature automatically: "
        '"all" or "drop_folder" (only quotes dropped in the inbox folder)'
    ),
    "value_type": "json",
    "value": "all",
}


def upgrade():
    op.execute(
        sa.text(
            "INSERT INTO business_rules (id, rule_key, category, display_name, description, value_type, "
            "current_value, default_value) VALUES (gen_random_uuid(), :k, :c, :n, :d, :t, "
            "CAST(:v AS JSONB), CAST(:v AS JSONB)) ON CONFLICT (rule_key) DO NOTHING"
        ).bindparams(
            k=RULE["rule_key"], c=RULE["category"], n=RULE["display_name"], d=RULE["description"],
            t=RULE["value_type"], v=json.dumps(RULE["value"]),
        )
    )


def downgrade():
    op.execute(sa.text("DELETE FROM business_rule_history WHERE rule_key = 'contract.auto_send_scope'"))
    op.execute(sa.text("DELETE FROM business_rules WHERE rule_key = 'contract.auto_send_scope'"))
