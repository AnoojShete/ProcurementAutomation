"""Prompt 11: Breach catalogue, GST identity matching, waivers, and Ruleset v2.

Revision ID: 0014
Revises: 0013
"""
import json
import hashlib
from alembic import op
from sqlalchemy import text
from app.services.scorecard.ruleset_v2 import RULESET_V2_DEFINITION

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade():
    # 1. Breach catalogue tables
    op.execute("""
        CREATE TABLE IF NOT EXISTS breach_catalogue (
            name TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            domain TEXT,
            breach_date DATE NOT NULL,
            added_date TIMESTAMPTZ NOT NULL,
            pwn_count BIGINT NOT NULL,
            data_classes JSONB NOT NULL,
            description TEXT,
            is_verified BOOLEAN NOT NULL DEFAULT true,
            is_fabricated BOOLEAN NOT NULL DEFAULT false,
            is_sensitive BOOLEAN NOT NULL DEFAULT false,
            is_retired BOOLEAN NOT NULL DEFAULT false,
            is_spam_list BOOLEAN NOT NULL DEFAULT false,
            is_malware BOOLEAN NOT NULL DEFAULT false,
            catalogue_version TEXT NOT NULL,
            fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS idx_breach_catalogue_domain ON breach_catalogue (domain);
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS breach_catalogue_meta (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            version_sha256 TEXT NOT NULL,
            fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            record_count INT NOT NULL,
            source TEXT NOT NULL,
            uploaded_by TEXT,
            raw_object_key TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_breach_catalogue_meta_fetched_at ON breach_catalogue_meta (fetched_at DESC);
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS breach_vendor_reviews (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            vendor_id UUID NOT NULL REFERENCES vendors(id) ON DELETE CASCADE,
            breach_name TEXT NOT NULL,
            decision TEXT NOT NULL CHECK (decision IN ('same_entity', 'different_entity')),
            notes TEXT NOT NULL,
            reviewer_id TEXT NOT NULL,
            reviewed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_breach_vendor_review UNIQUE (vendor_id, breach_name)
        );
        CREATE INDEX IF NOT EXISTS idx_breach_vendor_reviews_vendor ON breach_vendor_reviews (vendor_id);
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS vendor_waivers (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            vendor_id UUID NOT NULL REFERENCES vendors(id) ON DELETE CASCADE,
            waiver_type TEXT NOT NULL,
            certification_name TEXT,
            rationale TEXT NOT NULL,
            approved_by TEXT NOT NULL,
            approved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            valid_until TIMESTAMPTZ NOT NULL,
            active BOOLEAN NOT NULL DEFAULT true
        );
        CREATE INDEX IF NOT EXISTS idx_vendor_waivers_vendor ON vendor_waivers (vendor_id);
    """)

    # 2. Add columns on vendors
    op.execute("ALTER TABLE vendors ADD COLUMN IF NOT EXISTS onboarded_by VARCHAR(255)")
    op.execute("ALTER TABLE vendors ADD COLUMN IF NOT EXISTS created_by VARCHAR(255)")

    # 3. Retire v1 and seed/activate ruleset v2
    canonical = json.dumps(RULESET_V2_DEFINITION, sort_keys=True, separators=(",", ":"))
    chash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    def_json = json.dumps(RULESET_V2_DEFINITION)

    op.execute("UPDATE risk_rulesets SET status = 'retired' WHERE version = 1")
    
    conn = op.get_bind()
    conn.execute(
        text("""
            INSERT INTO risk_rulesets (
                id, version, status, definition, definition_hash, created_by, activated_by, activated_at, change_justification
            ) VALUES (
                gen_random_uuid(), 2, 'active', CAST(:definition AS jsonb), :hash, 'system', 'system', now(), 'Prompt 11: Live-test fixes ruleset v2'
            )
            ON CONFLICT (version) DO UPDATE SET
                definition = EXCLUDED.definition,
                definition_hash = EXCLUDED.definition_hash,
                status = 'active',
                activated_at = now()
        """),
        {"definition": def_json, "hash": chash}
    )


def downgrade():
    op.execute("UPDATE risk_rulesets SET status = 'retired' WHERE version = 2")
    op.execute("UPDATE risk_rulesets SET status = 'active' WHERE version = 1")
    op.execute("ALTER TABLE vendors DROP COLUMN IF EXISTS created_by")
    op.execute("ALTER TABLE vendors DROP COLUMN IF EXISTS onboarded_by")
    op.execute("DROP TABLE IF EXISTS vendor_waivers")
    op.execute("DROP TABLE IF EXISTS breach_vendor_reviews")
    op.execute("DROP TABLE IF EXISTS breach_catalogue_meta")
    op.execute("DROP TABLE IF EXISTS breach_catalogue")
