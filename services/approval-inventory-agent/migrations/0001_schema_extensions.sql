-- Schema extensions this service's ORM models (app/models.py) require on
-- top of shared/db/init.sql. Never edit init.sql directly — this file is
-- applied idempotently (IF NOT EXISTS everywhere) at startup by
-- app/database.py's init_db(), the same pattern contract-risk-agent uses
-- via Alembic. Written to unblock running this already-implemented
-- service against the real shared schema; no application logic changed.

ALTER TABLE vendors ADD COLUMN IF NOT EXISTS contact_email VARCHAR(255);
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS contact_phone VARCHAR(50);
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS address TEXT;
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS category VARCHAR(100);
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;
-- `status` may already exist (added by contract-risk-agent's migration).
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'active';

ALTER TABLE purchase_requests ADD COLUMN IF NOT EXISTS document_id UUID REFERENCES documents(id);
ALTER TABLE purchase_requests ADD COLUMN IF NOT EXISTS request_type VARCHAR(20);
ALTER TABLE purchase_requests ADD COLUMN IF NOT EXISTS spend_tier VARCHAR(20);
ALTER TABLE purchase_requests ADD COLUMN IF NOT EXISTS approval_chain JSONB;
ALTER TABLE purchase_requests ADD COLUMN IF NOT EXISTS current_approver_index INTEGER DEFAULT 0;
ALTER TABLE purchase_requests ADD COLUMN IF NOT EXISTS sla_deadline TIMESTAMPTZ;
ALTER TABLE purchase_requests ADD COLUMN IF NOT EXISTS backorder_parent_id UUID REFERENCES purchase_requests(id);
ALTER TABLE purchase_requests ADD COLUMN IF NOT EXISTS is_backordered BOOLEAN DEFAULT false;
ALTER TABLE purchase_requests ADD COLUMN IF NOT EXISTS comments TEXT;
ALTER TABLE purchase_requests ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;
-- `vendor_id` / `items` may already exist (added by contract-risk-agent's migration).
ALTER TABLE purchase_requests ADD COLUMN IF NOT EXISTS vendor_id UUID REFERENCES vendors(id);
ALTER TABLE purchase_requests ADD COLUMN IF NOT EXISTS items JSONB;

CREATE TABLE IF NOT EXISTS approval_history (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  request_id UUID NOT NULL REFERENCES purchase_requests(id),
  decision VARCHAR(20) NOT NULL,
  decided_by VARCHAR(255) NOT NULL,
  decision_level VARCHAR(50),
  escalated BOOLEAN DEFAULT false,
  comments TEXT,
  decided_at TIMESTAMPTZ
);

ALTER TABLE licenses ADD COLUMN IF NOT EXISTS cost_per_seat NUMERIC(10, 2);
ALTER TABLE licenses ADD COLUMN IF NOT EXISTS currency VARCHAR(3) DEFAULT 'INR';
ALTER TABLE licenses ADD COLUMN IF NOT EXISTS period_start DATE;
ALTER TABLE licenses ADD COLUMN IF NOT EXISTS period_end DATE;
ALTER TABLE licenses ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'active';
ALTER TABLE licenses ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;
ALTER TABLE licenses ADD COLUMN IF NOT EXISTS assigned_seats INTEGER DEFAULT 0;
ALTER TABLE licenses ADD COLUMN IF NOT EXISTS reclaim_cooldown_until TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS license_usage (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  license_id UUID NOT NULL REFERENCES licenses(id),
  user_email VARCHAR(255) NOT NULL,
  last_login_at TIMESTAMPTZ,
  login_count_30d INTEGER DEFAULT 0,
  login_count_60d INTEGER DEFAULT 0,
  login_count_90d INTEGER DEFAULT 0,
  updated_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS inventory (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  sku VARCHAR(100) NOT NULL UNIQUE,
  name VARCHAR(255) NOT NULL,
  category VARCHAR(50),
  total_quantity INTEGER NOT NULL DEFAULT 0,
  available_quantity INTEGER NOT NULL DEFAULT 0,
  reserved_quantity INTEGER NOT NULL DEFAULT 0,
  unit_cost NUMERIC(10, 2),
  currency VARCHAR(3) DEFAULT 'INR',
  location VARCHAR(255),
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ
);

-- audit_log already has (id, entity_id, entity_type, action, payload,
-- created_at) from init.sql; this service's activities.py additionally
-- writes performed_by/details.
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS performed_by VARCHAR(255);
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS details JSONB;

CREATE TABLE IF NOT EXISTS license_reclaim_history (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  license_id UUID NOT NULL REFERENCES licenses(id),
  event_type VARCHAR(50) NOT NULL,
  event_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  by_user VARCHAR(255),
  cooldown_set_until TIMESTAMPTZ,
  notes TEXT
);

ALTER TABLE licenses ADD COLUMN IF NOT EXISTS last_scored_at TIMESTAMPTZ;
ALTER TABLE licenses ADD COLUMN IF NOT EXISTS anomaly_score NUMERIC(5, 4);
ALTER TABLE licenses ADD COLUMN IF NOT EXISTS top_factors JSONB;


-- Order monitor snapshots (app/services/order_monitor.py): one row per
-- scheduled check, newest read by GET /orders/summary/latest.
CREATE TABLE IF NOT EXISTS order_status_summaries (
  id UUID PRIMARY KEY,
  generated_at TIMESTAMPTZ NOT NULL,
  window_start TIMESTAMPTZ NOT NULL,
  trigger VARCHAR(20) NOT NULL DEFAULT 'scheduled',
  counts JSONB NOT NULL,
  changes JSONB NOT NULL,
  attention JSONB NOT NULL,
  open_order_value NUMERIC(14, 2),
  summary_text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_order_status_summaries_generated_at ON order_status_summaries (generated_at DESC);

-- Invoice ledger (app/services/invoice_ledger.py): what each invoice
-- booked against which purchase request line, and each invoice's outcome.
CREATE TABLE IF NOT EXISTS invoice_allocations (
  id UUID PRIMARY KEY,
  document_id UUID NOT NULL,
  purchase_request_id UUID NOT NULL REFERENCES purchase_requests(id),
  invoice_number VARCHAR(100),
  line_no INTEGER,
  description TEXT,
  quantity NUMERIC(12, 3),
  amount NUMERIC(14, 2) NOT NULL,
  payment_hold BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_invoice_allocations_request ON invoice_allocations (purchase_request_id);
CREATE INDEX IF NOT EXISTS idx_invoice_allocations_document ON invoice_allocations (document_id);

CREATE TABLE IF NOT EXISTS invoice_matches (
  document_id UUID PRIMARY KEY,
  vendor_id UUID,
  purchase_request_id UUID,
  invoice_number VARCHAR(100),
  status VARCHAR(20) NOT NULL,
  amount NUMERIC(14, 2),
  payment_hold BOOLEAN NOT NULL DEFAULT false,
  hold_reason TEXT,
  result JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Approval authority (app/services/approval_authority.py).
CREATE TABLE IF NOT EXISTS approver_assignments (
  id UUID PRIMARY KEY,
  level VARCHAR(50) NOT NULL,
  user_email VARCHAR(255) NOT NULL,
  max_amount NUMERIC(14, 2),
  active BOOLEAN NOT NULL DEFAULT true,
  created_by VARCHAR(255),
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE (level, user_email)
);
CREATE TABLE IF NOT EXISTS approval_delegations (
  id UUID PRIMARY KEY,
  level VARCHAR(50) NOT NULL,
  delegator_email VARCHAR(255) NOT NULL,
  delegate_email VARCHAR(255) NOT NULL,
  valid_from TIMESTAMPTZ NOT NULL,
  valid_until TIMESTAMPTZ NOT NULL,
  reason TEXT,
  created_by VARCHAR(255),
  created_at TIMESTAMPTZ DEFAULT now(),
  revoked_at TIMESTAMPTZ
);

-- Demo authority matrix, matching the seeded demo accounts. Admin is
-- assigned to both levels so a single admin can still demo either one,
-- but separation of duties still stops them approving their own request
-- or both levels of the same request.
INSERT INTO approver_assignments (id, level, user_email, max_amount, created_by) VALUES
  ('a0000000-0000-4000-8000-000000000001', 'dept_manager', 'approver@demo.example.com', NULL, 'seed'),
  ('a0000000-0000-4000-8000-000000000002', 'finance_head', 'finance@demo.example.com', NULL, 'seed'),
  ('a0000000-0000-4000-8000-000000000003', 'dept_manager', 'admin@demo.example.com', NULL, 'seed'),
  ('a0000000-0000-4000-8000-000000000004', 'finance_head', 'admin@demo.example.com', NULL, 'seed')
ON CONFLICT (level, user_email) DO NOTHING
;

-- Backfill: invoices matched before the ledger existed (their match lives
-- only in documents.extracted.matched_po_id). Without this their requests
-- look un-invoiced and a new invoice could be booked against them again.
-- Idempotent: skips documents already in the ledger.
INSERT INTO invoice_matches (document_id, vendor_id, purchase_request_id, invoice_number, status, amount, result, created_at)
SELECT d.id, d.vendor_id, (d.extracted->>'matched_po_id')::uuid, d.extracted->>'invoice_number', 'matched', d.total,
       jsonb_build_object('status', 'matched', 'request_id', d.extracted->>'matched_po_id', 'amount', d.total,
                          'allocations', '[]'::jsonb, 'issues', jsonb_build_array('booked by the pre-ledger matcher (backfilled)'),
                          'remaining_before', NULL, 'remaining_after', NULL, 'candidates', '[]'::jsonb),
       COALESCE(d.updated_at, now())
FROM documents d
WHERE d.document_type = 'invoice' AND d.total IS NOT NULL
  AND d.extracted->>'matched_po_id' ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
  AND EXISTS (SELECT 1 FROM purchase_requests pr WHERE pr.id = (d.extracted->>'matched_po_id')::uuid)
  AND NOT EXISTS (SELECT 1 FROM invoice_matches m WHERE m.document_id = d.id)
;

INSERT INTO invoice_allocations (id, document_id, purchase_request_id, invoice_number, line_no, description, quantity, amount, created_at)
SELECT gen_random_uuid(), m.document_id, m.purchase_request_id, m.invoice_number, NULL, 'pre-ledger match (backfilled)', NULL, m.amount, m.created_at
FROM invoice_matches m
WHERE m.result->'issues' ? 'booked by the pre-ledger matcher (backfilled)'
  AND NOT EXISTS (SELECT 1 FROM invoice_allocations a WHERE a.document_id = m.document_id)
;

-- The old contract.signed handler moved already-invoiced requests back to
-- 'fulfilled'. Put them where the lifecycle says they are, and record why.
INSERT INTO audit_log (id, entity_type, entity_id, action, performed_by, details, created_at)
SELECT gen_random_uuid(), 'purchase_request', pr.id, 'status_corrected', 'migration:invoice_ledger_backfill',
       jsonb_build_object('from', 'fulfilled', 'to', 'invoice_received', 'reason', 'invoiced before the contract was signed, and the old handler moved it backwards'),
       now()
FROM purchase_requests pr
WHERE pr.status = 'fulfilled'
  AND EXISTS (SELECT 1 FROM invoice_matches m WHERE m.purchase_request_id = pr.id AND m.status = 'matched')
;
UPDATE purchase_requests pr SET status = 'invoice_received', updated_at = now()
WHERE pr.status = 'fulfilled'
  AND EXISTS (SELECT 1 FROM invoice_matches m WHERE m.purchase_request_id = pr.id AND m.status = 'matched')
;

-- Integrity (Sep 26): foreign keys, allowed values, indexes for hot
-- queries. Safe to re-run; existing data was checked and satisfies them.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_invoice_matches_document') THEN
    ALTER TABLE invoice_matches ADD CONSTRAINT fk_invoice_matches_document
      FOREIGN KEY (document_id) REFERENCES documents(id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_invoice_matches_request') THEN
    ALTER TABLE invoice_matches ADD CONSTRAINT fk_invoice_matches_request
      FOREIGN KEY (purchase_request_id) REFERENCES purchase_requests(id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_invoice_matches_vendor') THEN
    ALTER TABLE invoice_matches ADD CONSTRAINT fk_invoice_matches_vendor
      FOREIGN KEY (vendor_id) REFERENCES vendors(id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_invoice_allocations_document') THEN
    ALTER TABLE invoice_allocations ADD CONSTRAINT fk_invoice_allocations_document
      FOREIGN KEY (document_id) REFERENCES documents(id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_purchase_requests_status') THEN
    ALTER TABLE purchase_requests ADD CONSTRAINT ck_purchase_requests_status CHECK (status IN (
      'pending_approval', 'pending_grace_period', 'backordered', 'approved', 'fulfilled',
      'partially_invoiced', 'invoice_received', 'rejected', 'cancelled', 'split'));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_purchase_requests_amount') THEN
    ALTER TABLE purchase_requests ADD CONSTRAINT ck_purchase_requests_amount CHECK (amount >= 0);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_invoice_matches_status') THEN
    ALTER TABLE invoice_matches ADD CONSTRAINT ck_invoice_matches_status
      CHECK (status IN ('matched', 'partial', 'variance', 'ambiguous', 'no_match'));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_approver_assignments_limit') THEN
    ALTER TABLE approver_assignments ADD CONSTRAINT ck_approver_assignments_limit
      CHECK (max_amount IS NULL OR max_amount >= 0);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_approval_delegations_window') THEN
    ALTER TABLE approval_delegations ADD CONSTRAINT ck_approval_delegations_window CHECK (valid_until > valid_from);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_purchase_requests_requester ON purchase_requests (lower(requested_by), created_at DESC);
CREATE INDEX IF NOT EXISTS idx_purchase_requests_status ON purchase_requests (status);
CREATE INDEX IF NOT EXISTS idx_purchase_requests_vendor ON purchase_requests (vendor_id);
CREATE INDEX IF NOT EXISTS idx_approval_history_request ON approval_history (request_id);
CREATE INDEX IF NOT EXISTS idx_invoice_matches_request ON invoice_matches (purchase_request_id);
CREATE INDEX IF NOT EXISTS idx_invoice_matches_held ON invoice_matches (vendor_id) WHERE payment_hold
