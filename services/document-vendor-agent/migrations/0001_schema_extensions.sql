-- Schema extensions this service's ORM models (app/models.py) require on
-- top of shared/db/init.sql. Never edit init.sql directly — this file is
-- applied idempotently (IF NOT EXISTS everywhere) at startup by
-- app/database.py's init_db(), the same raw-SQL pattern
-- approval-inventory-agent uses (see its migrations/0001_schema_extensions.sql).
-- Every statement is safe to run whether or not another service's own
-- migration already touched these shared tables.

-- documents: shared table already has id, vendor_id, document_type,
-- extracted, confidence, needs_review, created_at.
ALTER TABLE documents ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'pending';
ALTER TABLE documents ADD COLUMN IF NOT EXISTS file_type VARCHAR(10);
ALTER TABLE documents ADD COLUMN IF NOT EXISTS minio_path TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS original_filename TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS uploaded_by VARCHAR(255);
ALTER TABLE documents ADD COLUMN IF NOT EXISTS uploaded_at TIMESTAMPTZ;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS vendor_name_raw TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS document_number VARCHAR(100);
ALTER TABLE documents ADD COLUMN IF NOT EXISTS document_date DATE;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS total NUMERIC(14, 2);
ALTER TABLE documents ADD COLUMN IF NOT EXISTS currency VARCHAR(10);
ALTER TABLE documents ADD COLUMN IF NOT EXISTS overall_confidence NUMERIC(4, 3);
ALTER TABLE documents ADD COLUMN IF NOT EXISTS is_likely_duplicate BOOLEAN DEFAULT false;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS duplicate_of_document_id UUID REFERENCES documents(id);
ALTER TABLE documents ADD COLUMN IF NOT EXISTS reviewed_by VARCHAR(255);
ALTER TABLE documents ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS error_message TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;

-- vendors: shared table already has id, name, normalized_name, created_at.
-- `status`/`contact_email`/etc may already exist courtesy of another
-- service's migration (contract-risk-agent / approval-inventory-agent) —
-- IF NOT EXISTS makes the ordering irrelevant.
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'active';
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS bank_account_number TEXT;
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS routing_code TEXT;
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS payment_beneficiary_name TEXT;
-- BEC-fraud control: true whenever there is an unresolved change request
-- against this vendor's bank/payment details. OLD (live) payment fields
-- above remain authoritative for any pending/future payment while true.
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS payment_details_pending_verification BOOLEAN DEFAULT false;
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;

-- GSTIN verification columns (document-vendor-agent, Prompt 1).
-- UNIQUE INDEX prevents two concurrent vendor-creation requests with the
-- same GSTIN from both inserting (a DB-level constraint, not just app-level).
-- Partial index (WHERE gstin IS NOT NULL) so NULLs don't conflict with each other.
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS gstin VARCHAR(15);
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS gstin_verification_status VARCHAR(20) DEFAULT 'unverified';
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS gstin_data_source VARCHAR(20);
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS gstin_cached_response JSONB;
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS gstin_cached_at TIMESTAMPTZ;
CREATE UNIQUE INDEX IF NOT EXISTS vendors_gstin_unique ON vendors(gstin) WHERE gstin IS NOT NULL;

-- Tiered vetting + spend tracking (structuring detection)
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS vendor_tier VARCHAR(10) DEFAULT 'standard';
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS cumulative_spend_90d NUMERIC(14, 2) DEFAULT 0;
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS spend_last_reset_at TIMESTAMPTZ;

-- No-GSTIN attestation (logged when onboarding a petty/sub-threshold vendor)
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS no_gstin_confirmed_by VARCHAR(255);
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS no_gstin_confirmed_at TIMESTAMPTZ;

-- Dual-control queue for bank/payment-detail changes on EXISTING vendors.
-- A row here never auto-applies to vendors.bank_account_number etc — only
-- POST /vendors/{id}/verify-payment-change, by a DIFFERENT user than
-- submitted_by, moves it to status='verified' and copies the new_* fields
-- onto the live vendor row.
CREATE TABLE IF NOT EXISTS vendor_payment_change_requests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  vendor_id UUID NOT NULL REFERENCES vendors(id),
  submitted_by VARCHAR(255) NOT NULL,
  submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  source VARCHAR(30) NOT NULL, -- portal | email | api | document
  document_id UUID REFERENCES documents(id),
  previous_bank_account_number TEXT,
  previous_routing_code TEXT,
  previous_beneficiary_name TEXT,
  new_bank_account_number TEXT,
  new_routing_code TEXT,
  new_beneficiary_name TEXT,
  status VARCHAR(20) NOT NULL DEFAULT 'pending', -- pending | verified | rejected
  verified_by VARCHAR(255),
  verified_at TIMESTAMPTZ,
  verification_channel VARCHAR(50),
  verification_notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- audit_log already has (id, entity_id, entity_type, action, payload,
-- created_at) from init.sql; this service writes verifier/channel/reject
-- details inside `payload` per the platform convention, no new columns.

-- Per-stage diagnostic trail for the document pipeline
-- (app/services/pipeline.py / app/services/checkpoints.py). Not part of
-- the business transaction — a write failure here never fails real
-- document processing (see checkpoints.py's try/except).
CREATE TABLE IF NOT EXISTS pipeline_checkpoints (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id UUID NOT NULL REFERENCES documents(id),
  stage_index INT NOT NULL,
  agent_name VARCHAR(50) NOT NULL,
  agent_version VARCHAR(20) NOT NULL,
  task_id UUID NOT NULL,
  confidence NUMERIC(4, 3),
  validation_status VARCHAR(20) NOT NULL DEFAULT 'valid',
  errors JSONB,
  warnings JSONB,
  duration_ms NUMERIC(10, 2),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
