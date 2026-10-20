"""Deterministic rule-based vendor risk scorecard (Prompt 9B).

Creates:
- risk_rulesets
- vendor_signal_raw_responses
- vendor_signal_observations
- risk_score_rule_results
- vendor_assessment_disputes
- vendor_evidence
Extends:
- risk_scores (additive columns for deterministic ruleset scoring)
Adds:
- Append-only DB triggers on raw_responses, observations, scores, and rule_results.
"""
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    # 1. risk_rulesets
    op.execute("""
        CREATE TABLE IF NOT EXISTS risk_rulesets (
            id UUID PRIMARY KEY,
            version INT UNIQUE NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('draft', 'active', 'retired')),
            definition JSONB NOT NULL,
            definition_hash TEXT NOT NULL,
            created_by TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            activated_by TEXT,
            activated_at TIMESTAMPTZ,
            change_justification TEXT,
            dry_run_report JSONB
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_risk_rulesets_status ON risk_rulesets (status)")

    # 2. vendor_signal_raw_responses
    op.execute("""
        CREATE TABLE IF NOT EXISTS vendor_signal_raw_responses (
            id UUID PRIMARY KEY,
            vendor_id UUID NOT NULL REFERENCES vendors(id),
            signal_key TEXT NOT NULL,
            source_id TEXT,
            provider TEXT NOT NULL,
            request_method TEXT NOT NULL,
            request_url_redacted TEXT,
            request_params_redacted JSONB,
            response_status INT,
            response_headers_subset JSONB,
            body_text TEXT,
            body_object_key TEXT,
            body_sha256 TEXT NOT NULL,
            body_bytes INT NOT NULL,
            fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            duration_ms INT NOT NULL DEFAULT 0,
            error TEXT,
            retention_until DATE NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_raw_resp_vendor ON vendor_signal_raw_responses (vendor_id, signal_key, fetched_at DESC)")

    # 3. vendor_signal_observations
    op.execute("""
        CREATE TABLE IF NOT EXISTS vendor_signal_observations (
            id UUID PRIMARY KEY,
            vendor_id UUID NOT NULL REFERENCES vendors(id),
            signal_key TEXT NOT NULL,
            source_id TEXT,
            source_name TEXT NOT NULL,
            provider TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('ok', 'error', 'rate_limited', 'not_checked', 'not_applicable')),
            facts JSONB NOT NULL DEFAULT '[]'::jsonb,
            fields JSONB NOT NULL DEFAULT '{}'::jsonb,
            observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at TIMESTAMPTZ,
            raw_response_id UUID REFERENCES vendor_signal_raw_responses(id),
            evidence_id UUID,
            record_refs JSONB DEFAULT '[]'::jsonb,
            created_by TEXT NOT NULL DEFAULT 'system',
            manual_correction BOOLEAN NOT NULL DEFAULT false,
            correction_reason TEXT,
            corrects_observation_id UUID
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_obs_vendor_signal ON vendor_signal_observations (vendor_id, signal_key, fetched_at DESC)")

    # 4. vendor_evidence (evidence register)
    op.execute("""
        CREATE TABLE IF NOT EXISTS vendor_evidence (
            id UUID PRIMARY KEY,
            vendor_id UUID NOT NULL REFERENCES vendors(id),
            evidence_type TEXT NOT NULL,
            title TEXT NOT NULL,
            document_id UUID,
            file_key TEXT,
            status TEXT NOT NULL DEFAULT 'pending_review' CHECK (status IN ('pending_review', 'accepted', 'rejected', 'expired')),
            metadata JSONB DEFAULT '{}'::jsonb,
            valid_from DATE,
            valid_until DATE,
            scope_covers_service BOOLEAN NOT NULL DEFAULT true,
            verified_by TEXT,
            verified_at TIMESTAMPTZ,
            notes TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_evidence_vendor ON vendor_evidence (vendor_id, evidence_type, status)")

    # 5. Extend risk_scores
    op.execute("ALTER TABLE risk_scores ADD COLUMN IF NOT EXISTS ruleset_id UUID REFERENCES risk_rulesets(id)")
    op.execute("ALTER TABLE risk_scores ADD COLUMN IF NOT EXISTS ruleset_version INT")
    op.execute("ALTER TABLE risk_scores ADD COLUMN IF NOT EXISTS total_points INT")
    op.execute("ALTER TABLE risk_scores ADD COLUMN IF NOT EXISTS points_band TEXT")
    op.execute("ALTER TABLE risk_scores ADD COLUMN IF NOT EXISTS final_band TEXT")
    op.execute("ALTER TABLE risk_scores ADD COLUMN IF NOT EXISTS override_rule_ids JSONB DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE risk_scores ADD COLUMN IF NOT EXISTS unassessed_potential_points INT DEFAULT 0")
    op.execute("ALTER TABLE risk_scores ADD COLUMN IF NOT EXISTS worst_case_points INT DEFAULT 0")
    op.execute("ALTER TABLE risk_scores ADD COLUMN IF NOT EXISTS worst_case_band TEXT")
    op.execute("ALTER TABLE risk_scores ADD COLUMN IF NOT EXISTS is_provisional BOOLEAN DEFAULT false")
    op.execute("ALTER TABLE risk_scores ADD COLUMN IF NOT EXISTS provisional_reasons JSONB DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE risk_scores ADD COLUMN IF NOT EXISTS effective_tier TEXT")
    op.execute("ALTER TABLE risk_scores ADD COLUMN IF NOT EXISTS headline TEXT")
    op.execute("ALTER TABLE risk_scores ADD COLUMN IF NOT EXISTS explanation JSONB")
    op.execute("ALTER TABLE risk_scores ADD COLUMN IF NOT EXISTS observation_ids JSONB DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE risk_scores ADD COLUMN IF NOT EXISTS snapshot JSONB")
    op.execute("ALTER TABLE risk_scores ADD COLUMN IF NOT EXISTS snapshot_sha256 TEXT")
    op.execute("ALTER TABLE risk_scores ADD COLUMN IF NOT EXISTS assessed_at TIMESTAMPTZ")
    op.execute("ALTER TABLE risk_scores ADD COLUMN IF NOT EXISTS trigger_type TEXT")
    op.execute("ALTER TABLE risk_scores ADD COLUMN IF NOT EXISTS trigger_ref TEXT")
    op.execute("ALTER TABLE risk_scores ADD COLUMN IF NOT EXISTS previous_score_id UUID REFERENCES risk_scores(id)")

    # 6. risk_score_rule_results
    op.execute("""
        CREATE TABLE IF NOT EXISTS risk_score_rule_results (
            id UUID PRIMARY KEY,
            score_id UUID NOT NULL REFERENCES risk_scores(id),
            order_index INT NOT NULL,
            signal_key TEXT NOT NULL,
            group_key TEXT NOT NULL,
            rule_id TEXT NOT NULL,
            rule_version_hash TEXT,
            status TEXT NOT NULL CHECK (status IN ('assessed', 'not_assessed', 'not_applicable', 'review_pending')),
            points INT NOT NULL,
            potential_points INT NOT NULL,
            override_band TEXT,
            observed_fields JSONB DEFAULT '{}'::jsonb,
            facts JSONB DEFAULT '[]'::jsonb,
            reason_text TEXT NOT NULL,
            rationale TEXT NOT NULL,
            observation_id UUID REFERENCES vendor_signal_observations(id),
            raw_response_id UUID REFERENCES vendor_signal_raw_responses(id),
            remediation JSONB DEFAULT '[]'::jsonb,
            remediable BOOLEAN NOT NULL DEFAULT true,
            ages_out_on DATE
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_rule_results_score ON risk_score_rule_results (score_id, order_index)")

    # 7. vendor_assessment_disputes
    op.execute("""
        CREATE TABLE IF NOT EXISTS vendor_assessment_disputes (
            id UUID PRIMARY KEY,
            score_id UUID NOT NULL REFERENCES risk_scores(id),
            rule_result_id UUID REFERENCES risk_score_rule_results(id),
            raised_by TEXT NOT NULL,
            raised_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            reason TEXT NOT NULL,
            evidence_id UUID REFERENCES vendor_evidence(id),
            status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'upheld', 'rejected')),
            reviewed_by TEXT,
            reviewed_at TIMESTAMPTZ,
            resolution_note TEXT,
            resulting_observation_id UUID REFERENCES vendor_signal_observations(id),
            resulting_score_id UUID REFERENCES risk_scores(id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_disputes_vendor_score ON vendor_assessment_disputes (score_id, status)")

    # 8. Append-only triggers
    op.execute("""
        CREATE OR REPLACE FUNCTION trg_prevent_update_delete()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'Table % is append-only: updates and deletes are forbidden', TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION trg_raw_responses_retention_purge()
        RETURNS TRIGGER AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'vendor_signal_raw_responses is append-only: deletes are forbidden';
            ELSIF TG_OP = 'UPDATE' THEN
                IF OLD.retention_until IS NOT NULL AND CURRENT_DATE >= OLD.retention_until
                   AND NEW.body_text IS NULL AND NEW.body_object_key IS NULL
                   AND NEW.id = OLD.id AND NEW.vendor_id = OLD.vendor_id
                   AND NEW.signal_key = OLD.signal_key AND NEW.body_sha256 = OLD.body_sha256 THEN
                    RETURN NEW;
                ELSE
                    RAISE EXCEPTION 'vendor_signal_raw_responses is append-only: updates are forbidden except for retention purge past retention_until';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("DROP TRIGGER IF EXISTS trg_append_only_raw_responses ON vendor_signal_raw_responses")
    op.execute("""
        CREATE TRIGGER trg_append_only_raw_responses
        BEFORE UPDATE OR DELETE ON vendor_signal_raw_responses
        FOR EACH ROW EXECUTE FUNCTION trg_raw_responses_retention_purge()
    """)

    op.execute("DROP TRIGGER IF EXISTS trg_append_only_observations ON vendor_signal_observations")
    op.execute("""
        CREATE TRIGGER trg_append_only_observations
        BEFORE UPDATE OR DELETE ON vendor_signal_observations
        FOR EACH ROW EXECUTE FUNCTION trg_prevent_update_delete()
    """)

    op.execute("DROP TRIGGER IF EXISTS trg_append_only_risk_scores ON risk_scores")
    op.execute("""
        CREATE TRIGGER trg_append_only_risk_scores
        BEFORE UPDATE OR DELETE ON risk_scores
        FOR EACH ROW EXECUTE FUNCTION trg_prevent_update_delete()
    """)

    op.execute("DROP TRIGGER IF EXISTS trg_append_only_rule_results ON risk_score_rule_results")
    op.execute("""
        CREATE TRIGGER trg_append_only_rule_results
        BEFORE UPDATE OR DELETE ON risk_score_rule_results
        FOR EACH ROW EXECUTE FUNCTION trg_prevent_update_delete()
    """)


def downgrade():
    op.execute("DROP TRIGGER IF EXISTS trg_append_only_rule_results ON risk_score_rule_results")
    op.execute("DROP TRIGGER IF EXISTS trg_append_only_risk_scores ON risk_scores")
    op.execute("DROP TRIGGER IF EXISTS trg_append_only_observations ON vendor_signal_observations")
    op.execute("DROP TRIGGER IF EXISTS trg_append_only_raw_responses ON vendor_signal_raw_responses")
    op.execute("DROP TABLE IF EXISTS vendor_assessment_disputes")
    op.execute("DROP TABLE IF EXISTS risk_score_rule_results")
    op.execute("DROP TABLE IF EXISTS vendor_evidence")
    op.execute("DROP TABLE IF EXISTS vendor_signal_observations")
    op.execute("DROP TABLE IF EXISTS vendor_signal_raw_responses")
    op.execute("DROP TABLE IF EXISTS risk_rulesets")
