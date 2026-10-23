-- Vendor status backstop trigger on INSERT/UPDATE, inherent_tier, swift_bic, bank_name, and website.

ALTER TABLE vendors ADD COLUMN IF NOT EXISTS inherent_tier TEXT DEFAULT NULL;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_vendors_inherent_tier') THEN
        ALTER TABLE vendors ADD CONSTRAINT chk_vendors_inherent_tier
            CHECK (inherent_tier IS NULL OR inherent_tier IN ('low', 'moderate', 'high', 'critical'));
    END IF;
END $$;

ALTER TABLE vendors ADD COLUMN IF NOT EXISTS swift_bic VARCHAR(11) DEFAULT NULL;
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS bank_name TEXT DEFAULT NULL;
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS website TEXT DEFAULT NULL;

ALTER TABLE vendors ALTER COLUMN status SET DEFAULT 'onboarding';

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

DROP TRIGGER IF EXISTS trg_check_vendor_activation ON vendors;
CREATE TRIGGER trg_check_vendor_activation
BEFORE INSERT OR UPDATE OF status ON vendors
FOR EACH ROW EXECUTE FUNCTION trg_vendor_status_activation_backstop();
