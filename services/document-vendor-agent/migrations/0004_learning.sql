-- Learning from reviewer corrections (app/services/learning.py).
ALTER TABLE documents ADD COLUMN IF NOT EXISTS raw_text TEXT;

CREATE TABLE IF NOT EXISTS extraction_feedback (
  id UUID PRIMARY KEY,
  document_id UUID NOT NULL REFERENCES documents(id),
  vendor_id UUID,
  field VARCHAR(50) NOT NULL,
  original_value TEXT,
  corrected_value TEXT,
  label VARCHAR(60),
  reviewer VARCHAR(255),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_extraction_feedback_vendor ON extraction_feedback (vendor_id, field);

CREATE TABLE IF NOT EXISTS vendor_field_hints (
  vendor_id UUID NOT NULL,
  field VARCHAR(50) NOT NULL,
  label VARCHAR(60) NOT NULL,
  support INTEGER NOT NULL DEFAULT 1,
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (vendor_id, field, label)
);

CREATE TABLE IF NOT EXISTS review_outcomes (
  document_id UUID PRIMARY KEY REFERENCES documents(id),
  vendor_id UUID,
  fields_corrected INTEGER NOT NULL,
  corrected_fields JSONB NOT NULL,
  reviewer VARCHAR(255),
  reviewed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_review_outcomes_vendor ON review_outcomes (vendor_id, reviewed_at DESC)
