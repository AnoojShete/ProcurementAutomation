"""Prompt 11: seed the rules the breach catalogue, certification check and
batch upload read (they were read with code fallbacks only, so an admin
couldn't change them). Insert-only, idempotent.

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-29
"""
from alembic import op
import sqlalchemy as sa

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

RULES = [
    ("risk.breach_catalogue_max_age_days", "risk", "Breach Catalogue Max Age (days)",
     "A downloaded Have I Been Pwned catalogue older than this no longer counts; breach history becomes not assessed",
     "int", "30", 1, 365),
    ("risk.breach_name_match_pct", "risk", "Breach Name Match Threshold (%)",
     "A breach whose name is at least this similar to the vendor's name is a candidate match a reviewer must confirm",
     "int", "85", 50, 100),
    ("risk.required_certifications_by_tier", "risk", "Required Security Certifications by Tier",
     "Certifications a vendor of each tier must hold (an empty list means none required)",
     "json", '{"critical": ["ISO 27001 or SOC 2 report covering the service"], '
             '"high": ["ISO 27001 or SOC 2 report covering the service"], "moderate": [], "low": []}',
     None, None),
    ("document.upload_max_files_per_batch", "document", "Max Files per Upload Batch",
     "Most files one multi-file or folder upload may contain",
     "int", "500", 1, 5000),
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
