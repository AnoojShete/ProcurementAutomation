"""Vendor status backstop trigger on INSERT/UPDATE, inherent_tier, swift_bic, bank_name, and website.

Revision ID: 0012
Revises: 0011
"""
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade():
    # 1. Add inherent_tier, swift_bic, bank_name, website to vendors
    op.execute("ALTER TABLE vendors ADD COLUMN IF NOT EXISTS inherent_tier TEXT DEFAULT NULL")
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_vendors_inherent_tier') THEN
                ALTER TABLE vendors ADD CONSTRAINT chk_vendors_inherent_tier
                    CHECK (inherent_tier IS NULL OR inherent_tier IN ('low', 'moderate', 'high', 'critical'));
            END IF;
        END $$;
    """)

    op.execute("ALTER TABLE vendors ADD COLUMN IF NOT EXISTS swift_bic VARCHAR(11) DEFAULT NULL")
    op.execute("ALTER TABLE vendors ADD COLUMN IF NOT EXISTS bank_name TEXT DEFAULT NULL")
    op.execute("ALTER TABLE vendors ADD COLUMN IF NOT EXISTS website TEXT DEFAULT NULL")

    # Update default of vendors.status to 'onboarding'
    op.execute("ALTER TABLE vendors ALTER COLUMN status SET DEFAULT 'onboarding'")

    # 2. Update trg_vendor_status_activation_backstop trigger function
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
            IF TG_OP = 'INSERT' THEN
                IF NEW.status = 'active' THEN
                    IF NEW.activation_exempt_reason = 'petty_tier' THEN
                        RETURN NEW;
                    END IF;
                    RAISE EXCEPTION 'Vendor % cannot be created with active status without petty_tier exemption', NEW.id;
                END IF;
                RETURN NEW;
            END IF;

            IF TG_OP = 'UPDATE' THEN
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
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # 3. Re-create trigger on BEFORE INSERT OR UPDATE OF status ON vendors
    op.execute("DROP TRIGGER IF EXISTS trg_check_vendor_activation ON vendors")
    op.execute("""
        CREATE TRIGGER trg_check_vendor_activation
        BEFORE INSERT OR UPDATE OF status ON vendors
        FOR EACH ROW EXECUTE FUNCTION trg_vendor_status_activation_backstop();
    """)


def downgrade():
    op.execute("DROP TRIGGER IF EXISTS trg_check_vendor_activation ON vendors")
    op.execute("""
        CREATE TRIGGER trg_check_vendor_activation
        BEFORE UPDATE OF status ON vendors
        FOR EACH ROW EXECUTE FUNCTION trg_vendor_status_activation_backstop();
    """)
    op.execute("ALTER TABLE vendors DROP CONSTRAINT IF EXISTS chk_vendors_inherent_tier")
    op.execute("ALTER TABLE vendors DROP COLUMN IF EXISTS inherent_tier")
    op.execute("ALTER TABLE vendors DROP COLUMN IF EXISTS swift_bic")
    op.execute("ALTER TABLE vendors DROP COLUMN IF EXISTS bank_name")
    op.execute("ALTER TABLE vendors DROP COLUMN IF EXISTS website")
