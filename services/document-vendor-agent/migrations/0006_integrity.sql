-- Integrity for document-side tables: foreign keys, allowed values and
-- the indexes the pipeline's hot queries need. Every statement is safe to
-- re-run. Existing data was checked first: nothing violates these.

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_vendor_field_hints_vendor') THEN
    ALTER TABLE vendor_field_hints ADD CONSTRAINT fk_vendor_field_hints_vendor
      FOREIGN KEY (vendor_id) REFERENCES vendors(id) ON DELETE CASCADE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_extraction_feedback_vendor') THEN
    ALTER TABLE extraction_feedback ADD CONSTRAINT fk_extraction_feedback_vendor
      FOREIGN KEY (vendor_id) REFERENCES vendors(id) ON DELETE SET NULL;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_review_outcomes_vendor') THEN
    ALTER TABLE review_outcomes ADD CONSTRAINT fk_review_outcomes_vendor
      FOREIGN KEY (vendor_id) REFERENCES vendors(id) ON DELETE SET NULL;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_documents_status') THEN
    ALTER TABLE documents ADD CONSTRAINT ck_documents_status
      CHECK (status IN ('pending', 'processing', 'classified', 'failed'));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_documents_attempts') THEN
    ALTER TABLE documents ADD CONSTRAINT ck_documents_attempts CHECK (processing_attempts >= 0);
  END IF;
END $$;

-- "My documents" list, the stranded-document sweep, duplicate detection.
CREATE INDEX IF NOT EXISTS idx_documents_uploader ON documents (lower(uploaded_by), uploaded_at DESC);
CREATE INDEX IF NOT EXISTS idx_documents_unfinished ON documents (status, updated_at) WHERE status IN ('pending', 'processing');
CREATE INDEX IF NOT EXISTS idx_documents_vendor_type ON documents (vendor_id, document_type);
CREATE INDEX IF NOT EXISTS idx_pipeline_checkpoints_document ON pipeline_checkpoints (document_id);
CREATE INDEX IF NOT EXISTS idx_payment_changes_vendor_status ON vendor_payment_change_requests (vendor_id, status);
-- Audit trail lookups by entity (every service writes audit_log).
CREATE INDEX IF NOT EXISTS idx_audit_log_entity ON audit_log (entity_type, entity_id, created_at);
