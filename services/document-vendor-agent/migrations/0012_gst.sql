-- Feature expansion Phase 4 (docs/feature-expansion-plan.md): GST checks.
-- New tables and nullable columns only; no existing row changes.

-- Result of the tax check (app/services/tax_check.py), per invoice.
ALTER TABLE documents ADD COLUMN IF NOT EXISTS tax_check JSONB;

-- GST rate by HSN (goods) or SAC (services) code or code prefix; the
-- longest matching prefix wins. Seeded with the rates current in October
-- 2026 for IT purchases; finance edits them on the GST page. A chartered
-- accountant must confirm them before use.
CREATE TABLE IF NOT EXISTS gst_rates (
  code VARCHAR(8) PRIMARY KEY,
  description TEXT NOT NULL,
  category VARCHAR(20) NOT NULL,            -- hardware | software | saas | services
  rate_pct NUMERIC(5, 2) NOT NULL,
  updated_by VARCHAR(255),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_gst_rates_values') THEN
    ALTER TABLE gst_rates ADD CONSTRAINT ck_gst_rates_values CHECK (
      rate_pct >= 0 AND rate_pct <= 40 AND code ~ '^[0-9]{4,8}$'
      AND category IN ('hardware', 'software', 'saas', 'services'));
  END IF;
END $$;
INSERT INTO gst_rates (code, description, category, rate_pct) VALUES
  ('8471', 'Computers, laptops, servers and storage', 'hardware', 18),
  ('8473', 'Parts and accessories of computers', 'hardware', 18),
  ('8443', 'Printers and multifunction devices', 'hardware', 18),
  ('8517', 'Network equipment: switches, routers, phones', 'hardware', 18),
  ('8528', 'Monitors and projectors', 'hardware', 18),
  ('8504', 'UPS and power supplies', 'hardware', 18),
  ('8523', 'Software on physical media', 'software', 18),
  ('997331', 'Licensing of software', 'software', 18),
  ('998313', 'IT consulting and support', 'services', 18),
  ('998314', 'IT design and development', 'services', 18),
  ('998315', 'Hosting and IT infrastructure provisioning', 'saas', 18),
  ('998316', 'IT infrastructure and network management', 'services', 18),
  ('998319', 'Other IT services', 'services', 18),
  ('998431', 'Online information and database access (SaaS)', 'saas', 18),
  ('998713', 'Maintenance and repair of computers', 'services', 18)
ON CONFLICT (code) DO NOTHING;

-- GSTR-2B files uploaded by finance and what they reconciled to.
CREATE TABLE IF NOT EXISTS gstr2b_uploads (
  id UUID PRIMARY KEY,
  period VARCHAR(6) NOT NULL,               -- MMYYYY, as in the file
  buyer_gstin VARCHAR(15),
  filename TEXT,
  uploaded_by VARCHAR(255) NOT NULL,
  uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  summary JSONB NOT NULL,
  results JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_gstr2b_uploads_period ON gstr2b_uploads (period, uploaded_at DESC);

-- Vendor tax profile (edited through approval-inventory-agent's /tds API,
-- which adds the same columns; whichever service starts first creates them).
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS pan VARCHAR(10);
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS tds_section VARCHAR(12);
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS ldc_rate_pct NUMERIC(5, 2);
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS ldc_valid_until DATE;
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS msme_udyam_number VARCHAR(19);
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS msme_category VARCHAR(10);
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS annual_turnover_inr NUMERIC(16, 2);
