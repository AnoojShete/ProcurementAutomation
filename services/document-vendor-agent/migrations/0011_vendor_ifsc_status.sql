-- FR-14: the IFSC directory result for a vendor's bank code (valid |
-- invalid | pending), so the risk model's IFSC hard check can fire.
-- contract-risk-agent adds the same column; IF NOT EXISTS keeps order irrelevant.
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS ifsc_verification_status TEXT;
