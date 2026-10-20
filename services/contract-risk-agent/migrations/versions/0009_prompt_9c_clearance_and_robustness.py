"""Data model additions for Prompt 9C: Vendor clearance, rating status, robustness, backstop trigger.

Revision ID: 0009
Revises: 0008
"""
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    # 1. Update risk_scores table
    op.execute("ALTER TABLE risk_scores ADD COLUMN IF NOT EXISTS rating_status TEXT DEFAULT 'not_rated'")
    op.execute("ALTER TABLE risk_scores ADD COLUMN IF NOT EXISTS assessed_share_pct INT DEFAULT 0")
    op.execute("ALTER TABLE risk_scores ADD COLUMN IF NOT EXISTS applicable_max_points INT DEFAULT 100")
    op.execute("ALTER TABLE risk_scores ADD COLUMN IF NOT EXISTS due_diligence_potential_points INT DEFAULT 0")
    op.execute("ALTER TABLE risk_scores ADD COLUMN IF NOT EXISTS history_potential_points INT DEFAULT 0")
    op.execute("ALTER TABLE risk_scores ADD COLUMN IF NOT EXISTS points_is_lower_bound BOOLEAN DEFAULT false")
    op.execute("ALTER TABLE risk_scores ADD COLUMN IF NOT EXISTS blocked_by JSONB DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE risk_scores ADD COLUMN IF NOT EXISTS remediation_path JSONB DEFAULT '[]'::jsonb")

    # Make risk_score legacy column nullable (NULL when rating_status != assessed)
    op.execute("ALTER TABLE risk_scores ALTER COLUMN score DROP NOT NULL")

    # Final band check constraint: Low, Medium, High, Unrated
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_risk_scores_final_band') THEN
                ALTER TABLE risk_scores DROP CONSTRAINT chk_risk_scores_final_band;
            END IF;
            ALTER TABLE risk_scores ADD CONSTRAINT chk_risk_scores_final_band
                CHECK (final_band IS NULL OR final_band IN ('Low', 'Medium', 'High', 'Unrated'));
        END $$;
    """)

    # 2. Update risk_score_rule_results table
    op.execute("ALTER TABLE risk_score_rule_results ADD COLUMN IF NOT EXISTS kind TEXT DEFAULT 'due_diligence'")
    op.execute("ALTER TABLE risk_score_rule_results ADD COLUMN IF NOT EXISTS coverage_type TEXT DEFAULT 'full'")

    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'risk_score_rule_results_status_check') THEN
                ALTER TABLE risk_score_rule_results DROP CONSTRAINT risk_score_rule_results_status_check;
            END IF;
            ALTER TABLE risk_score_rule_results ADD CONSTRAINT risk_score_rule_results_status_check
                CHECK (status IN ('assessed', 'assessed_no_finding', 'not_assessed', 'not_applicable', 'review_pending'));
        END $$;
    """)

    # 3. Update vendor_signal_observations table
    op.execute("ALTER TABLE vendor_signal_observations ADD COLUMN IF NOT EXISTS extraction JSONB DEFAULT NULL")
    op.execute("ALTER TABLE vendor_signal_observations ADD COLUMN IF NOT EXISTS skip_reason TEXT DEFAULT NULL")

    # 4. Update vendors table
    op.execute("ALTER TABLE vendors ADD COLUMN IF NOT EXISTS country VARCHAR(2) DEFAULT NULL")
    op.execute("ALTER TABLE vendors ADD COLUMN IF NOT EXISTS activation_exempt_reason TEXT DEFAULT NULL")

    # 5. Create vendor_decisions table
    op.execute("""
        CREATE TABLE IF NOT EXISTS vendor_decisions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            vendor_id UUID NOT NULL REFERENCES vendors(id),
            decision TEXT NOT NULL CHECK (decision IN ('approve', 'approve_with_conditions', 'accept_risk', 'reject')),
            decided_by TEXT NOT NULL,
            decided_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            justification TEXT,
            conditions JSONB DEFAULT '[]'::jsonb,
            expires_at TIMESTAMPTZ,
            score_id UUID REFERENCES risk_scores(id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_vendor_decisions_vendor_decided ON vendor_decisions (vendor_id, decided_at DESC)")

    # 6. Database Backstop Trigger on vendors
    op.execute("""
        CREATE OR REPLACE FUNCTION trg_vendor_status_activation_backstop()
        RETURNS TRIGGER AS $$
        DECLARE
            latest_rating_status TEXT;
            latest_final_band TEXT;
            latest_scored_at TIMESTAMPTZ;
            has_valid_decision BOOLEAN := FALSE;
            has_unexpired_accept_risk BOOLEAN := FALSE;
        BEGIN
            IF NEW.status = 'active' AND (OLD.status IS NULL OR OLD.status != 'active') THEN
                -- Check petty tier exemption
                IF NEW.activation_exempt_reason = 'petty_tier' THEN
                    RETURN NEW;
                END IF;

                -- Check unexpired accept_risk decision
                SELECT EXISTS (
                    SELECT 1 FROM vendor_decisions
                    WHERE vendor_id = NEW.id
                      AND decision = 'accept_risk'
                      AND (expires_at IS NULL OR expires_at > now())
                ) INTO has_unexpired_accept_risk;

                IF has_unexpired_accept_risk THEN
                    RETURN NEW;
                END IF;

                -- Check latest risk_scores row
                SELECT rating_status, final_band, scored_at
                INTO latest_rating_status, latest_final_band, latest_scored_at
                FROM risk_scores
                WHERE vendor_id = NEW.id
                ORDER BY scored_at DESC
                LIMIT 1;

                IF latest_rating_status = 'assessed' AND latest_final_band IN ('Low', 'Medium') AND latest_scored_at IS NOT NULL THEN
                    SELECT EXISTS (
                        SELECT 1 FROM vendor_decisions
                        WHERE vendor_id = NEW.id
                          AND decision IN ('approve', 'approve_with_conditions')
                          AND decided_at > latest_scored_at
                    ) INTO has_valid_decision;

                    IF has_valid_decision THEN
                        RETURN NEW;
                    END IF;
                END IF;

                RAISE EXCEPTION 'Vendor % cannot be activated: requires assessed rating in Low/Medium with subsequent approval, unexpired accept_risk, or petty_tier exemption', NEW.id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("DROP TRIGGER IF EXISTS trg_check_vendor_activation ON vendors")
    op.execute("""
        CREATE TRIGGER trg_check_vendor_activation
        BEFORE UPDATE OF status ON vendors
        FOR EACH ROW EXECUTE FUNCTION trg_vendor_status_activation_backstop();
    """)

    # 7. Safe Backfill of existing risk_scores (Section H: disable trigger during backfill)
    op.execute("""
        DO $$
        BEGIN
            ALTER TABLE risk_scores DISABLE TRIGGER USER;

            UPDATE risk_scores
            SET rating_status = CASE
                    WHEN is_provisional = true THEN 'provisional'
                    WHEN final_band IS NOT NULL AND final_band != 'Unrated' THEN 'assessed'
                    ELSE 'not_rated'
                END,
                assessed_share_pct = CASE
                    WHEN is_provisional = true THEN 40
                    WHEN final_band IS NOT NULL THEN 100
                    ELSE 0
                END,
                applicable_max_points = 100,
                due_diligence_potential_points = COALESCE(unassessed_potential_points, 0),
                history_potential_points = 0,
                points_is_lower_bound = (COALESCE(unassessed_potential_points, 0) > 0)
            WHERE rating_status IS NULL OR rating_status = 'not_rated';

            ALTER TABLE risk_scores ENABLE TRIGGER USER;
        END $$;
    """)

    # 8. Seed Business Rules seeds
    op.execute("""
        INSERT INTO business_rules (key, value, description, updated_by, updated_at)
        VALUES
            ('risk.min_assessed_share_pct', '50', 'Minimum assessed due diligence points percentage to leave provisional', 'system', now()),
            ('risk.provisional_acceptance_max_days', '30', 'Maximum duration in days for provisional risk acceptance', 'system', now()),
            ('risk.min_relationship_days', '90', 'Minimum days of relationship before history is considered available for incidents', 'system', now()),
            ('risk.home_country', '"IN"', 'Home country code for domestic GST and IFSC requirements', 'system', now()),
            ('collector.breaker_failures', '3', 'Consecutive failures before external source circuit breaker opens', 'system', now()),
            ('collector.breaker_open_minutes', '15', 'Minutes circuit breaker stays open before probing', 'system', now()),
            ('collector.overall_deadline_seconds', '45', 'Global deadline in seconds for parallel external collectors', 'system', now()),
            ('vendor.petty_tier_max_amount', '5000.00', 'Maximum purchase amount eligible for petty tier clearance exception', 'system', now())
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
    """)


def downgrade():
    op.execute("DROP TRIGGER IF EXISTS trg_check_vendor_activation ON vendors")
    op.execute("DROP FUNCTION IF EXISTS trg_vendor_status_activation_backstop()")
    op.execute("DROP TABLE IF EXISTS vendor_decisions")
    op.execute("ALTER TABLE vendors DROP COLUMN IF EXISTS activation_exempt_reason")
    op.execute("ALTER TABLE vendors DROP COLUMN IF EXISTS country")
    op.execute("ALTER TABLE vendor_signal_observations DROP COLUMN IF EXISTS skip_reason")
    op.execute("ALTER TABLE vendor_signal_observations DROP COLUMN IF EXISTS extraction")
    op.execute("ALTER TABLE risk_score_rule_results DROP COLUMN IF EXISTS coverage_type")
    op.execute("ALTER TABLE risk_score_rule_results DROP COLUMN IF EXISTS kind")
    op.execute("ALTER TABLE risk_scores DROP COLUMN IF EXISTS remediation_path")
    op.execute("ALTER TABLE risk_scores DROP COLUMN IF EXISTS blocked_by")
    op.execute("ALTER TABLE risk_scores DROP COLUMN IF EXISTS points_is_lower_bound")
    op.execute("ALTER TABLE risk_scores DROP COLUMN IF EXISTS history_potential_points")
    op.execute("ALTER TABLE risk_scores DROP COLUMN IF EXISTS due_diligence_potential_points")
    op.execute("ALTER TABLE risk_scores DROP COLUMN IF EXISTS applicable_max_points")
    op.execute("ALTER TABLE risk_scores DROP COLUMN IF EXISTS assessed_share_pct")
    op.execute("ALTER TABLE risk_scores DROP COLUMN IF EXISTS rating_status")
