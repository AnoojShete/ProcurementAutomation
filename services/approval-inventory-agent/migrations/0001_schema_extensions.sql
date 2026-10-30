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
  ('a0000000-0000-4000-8000-000000000004', 'finance_head', 'admin@demo.example.com', NULL, 'seed'),
  ('a0000000-0000-4000-8000-000000000005', 'dept_manager', 'v89714260@gmail.com', NULL, 'seed'),
  ('a0000000-0000-4000-8000-000000000006', 'finance_head', 'nirajsawant761@gmail.com', NULL, 'seed'),
  ('a0000000-0000-4000-8000-000000000007', 'dept_manager', 'approver2@demo.example.com', NULL, 'seed'),
  ('a0000000-0000-4000-8000-000000000008', 'dept_manager', 'approver3@demo.example.com', NULL, 'seed'),
  ('a0000000-0000-4000-8000-000000000009', 'dept_manager', 'approver4@demo.example.com', NULL, 'seed'),
  ('a0000000-0000-4000-8000-000000000010', 'finance_head', 'finance2@demo.example.com', NULL, 'seed')
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
CREATE INDEX IF NOT EXISTS idx_invoice_matches_held ON invoice_matches (vendor_id) WHERE payment_hold;

-- 'ordered': contract signed, waiting on the vendor; 'fulfilled' now means
-- the goods/licences were received. Widens the status check (no rows change).
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_purchase_requests_status')
     AND NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_purchase_requests_status'
                     AND pg_get_constraintdef(oid) LIKE '%''ordered''%') THEN  -- quoted: 'backordered' also contains ordered
    ALTER TABLE purchase_requests DROP CONSTRAINT ck_purchase_requests_status;
    ALTER TABLE purchase_requests ADD CONSTRAINT ck_purchase_requests_status CHECK (status IN (
      'pending_approval', 'pending_grace_period', 'backordered', 'approved', 'ordered', 'fulfilled',
      'partially_invoiced', 'invoice_received', 'rejected', 'cancelled', 'split'));
  END IF;
END $$;

-- BR-5: per-item reorder point / reorder quantity. NULL = use the rule
-- defaults (inventory.reorder_point_pct / inventory.min_reorder_pct).
ALTER TABLE inventory ADD COLUMN IF NOT EXISTS reorder_point INTEGER;
ALTER TABLE inventory ADD COLUMN IF NOT EXISTS reorder_quantity INTEGER;

-- QA audit (Oct 17): NaN passed ck_purchase_requests_amount (NaN sorts
-- above every number in Postgres), and one NaN row made GET /requests/
-- fail for every user. The API now rejects non-finite amounts; this keeps
-- the table safe from other writers too.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_purchase_requests_amount_finite') THEN
    ALTER TABLE purchase_requests ADD CONSTRAINT ck_purchase_requests_amount_finite
      CHECK (amount <> 'NaN'::numeric AND amount < 'Infinity'::numeric);
  END IF;
END $$;

-- Feature expansion Phase 1 (docs/feature-expansion-plan.md): budgets per
-- department x IT category x fiscal period. What a budget has used is not
-- stored: it is computed from the requests that point at it and the invoice
-- allocations booked against them (app/services/budget_service.py), so it
-- follows every status change (approval, rejection, cancellation, split)
-- without extra bookkeeping. New table and nullable columns: no existing
-- row changes.
CREATE TABLE IF NOT EXISTS budgets (
  id UUID PRIMARY KEY,
  fiscal_year VARCHAR(7) NOT NULL,          -- e.g. 2026-27
  period VARCHAR(2) NOT NULL,               -- Q1..Q4, or FY when the period type is annual
  department VARCHAR(255) NOT NULL,
  category VARCHAR(20) NOT NULL,            -- hardware | software | saas | services
  amount_inr NUMERIC(14, 2) NOT NULL,
  owner_email VARCHAR(255),
  created_by VARCHAR(255) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_budgets_scope
  ON budgets (fiscal_year, period, lower(department), category);
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_budgets_values') THEN
    ALTER TABLE budgets ADD CONSTRAINT ck_budgets_values CHECK (
      amount_inr >= 0 AND amount_inr <> 'NaN'::numeric
      AND category IN ('hardware', 'software', 'saas', 'services')
      AND period IN ('Q1', 'Q2', 'Q3', 'Q4', 'FY')
      AND fiscal_year ~ '^[0-9]{4}-[0-9]{2}$');
  END IF;
END $$;

ALTER TABLE purchase_requests ADD COLUMN IF NOT EXISTS budget_id UUID REFERENCES budgets(id);
ALTER TABLE purchase_requests ADD COLUMN IF NOT EXISTS budget_status VARCHAR(12);
ALTER TABLE purchase_requests ADD COLUMN IF NOT EXISTS budget_check JSONB;
CREATE INDEX IF NOT EXISTS idx_purchase_requests_budget ON purchase_requests (budget_id);
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_purchase_requests_budget_status') THEN
    ALTER TABLE purchase_requests ADD CONSTRAINT ck_purchase_requests_budget_status
      CHECK (budget_status IS NULL OR budget_status IN ('within', 'warning', 'over', 'no_budget'));
  END IF;
END $$;

-- Feature expansion Phase 3 (docs/feature-expansion-plan.md): IT catalog,
-- RFQ events, partial goods receipts. New tables, nullable columns, and one
-- widened status check (adds 'partially_received'; no existing row changes).
CREATE TABLE IF NOT EXISTS catalog_items (
  id UUID PRIMARY KEY,
  sku VARCHAR(64) NOT NULL,
  name VARCHAR(255) NOT NULL,
  category VARCHAR(20) NOT NULL,            -- hardware | software | saas | services
  vendor_id UUID REFERENCES vendors(id),
  contract_id UUID,                         -- where the price comes from (contract-risk's contracts)
  unit_price NUMERIC(12, 2) NOT NULL,
  currency VARCHAR(3) NOT NULL DEFAULT 'INR',
  spec JSONB NOT NULL DEFAULT '{}'::jsonb,
  inventory_sku VARCHAR(100),               -- stock first: reserved from inventory when available
  license_id UUID REFERENCES licenses(id),  -- SaaS seat add-on: receiving it adds seats
  lead_time_days INTEGER,
  warranty_months INTEGER,
  active BOOLEAN NOT NULL DEFAULT true,
  valid_until DATE,
  created_by VARCHAR(255) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_catalog_items_sku ON catalog_items (lower(sku));
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_catalog_items_values') THEN
    ALTER TABLE catalog_items ADD CONSTRAINT ck_catalog_items_values CHECK (
      unit_price >= 0 AND unit_price <> 'NaN'::numeric
      AND category IN ('hardware', 'software', 'saas', 'services')
      AND (lead_time_days IS NULL OR lead_time_days >= 0)
      AND (warranty_months IS NULL OR warranty_months >= 0));
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS rfq_events (
  id UUID PRIMARY KEY,
  reference VARCHAR(10) NOT NULL UNIQUE,    -- RFQ-XXXXXX, quoted by vendors on their quotes
  title VARCHAR(255) NOT NULL,
  department VARCHAR(255) NOT NULL,
  request_type VARCHAR(20) NOT NULL,
  items JSONB NOT NULL DEFAULT '[]'::jsonb,
  criteria JSONB NOT NULL,                  -- weights per criterion, summing to 1
  sealed BOOLEAN NOT NULL DEFAULT true,
  round INTEGER NOT NULL DEFAULT 1,
  deadline TIMESTAMPTZ NOT NULL,
  status VARCHAR(12) NOT NULL DEFAULT 'open',
  created_by VARCHAR(255) NOT NULL,
  awarded_vendor_id UUID,
  awarded_response_id UUID,
  awarded_request_id UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS rfq_invitations (
  rfq_id UUID NOT NULL REFERENCES rfq_events(id),
  vendor_id UUID NOT NULL REFERENCES vendors(id),
  round INTEGER NOT NULL DEFAULT 1,
  invited_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  responded_at TIMESTAMPTZ,
  declined_reason TEXT,
  PRIMARY KEY (rfq_id, vendor_id, round)
);
CREATE TABLE IF NOT EXISTS rfq_responses (
  id UUID PRIMARY KEY,
  rfq_id UUID NOT NULL REFERENCES rfq_events(id),
  vendor_id UUID NOT NULL REFERENCES vendors(id),
  round INTEGER NOT NULL,
  quote_id UUID,                            -- document-vendor-agent's vendor_quotes, when it came as a quote
  total_inr NUMERIC(14, 2) NOT NULL,
  lead_time_days INTEGER,
  warranty_months INTEGER,
  support_rating INTEGER,                   -- 1..5, the buyer's reading of the support terms
  support_terms TEXT,
  line_items JSONB NOT NULL DEFAULT '[]'::jsonb,
  source VARCHAR(10) NOT NULL DEFAULT 'manual',
  submitted_by VARCHAR(255),
  submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (rfq_id, vendor_id, round)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_rfq_responses_quote ON rfq_responses (quote_id) WHERE quote_id IS NOT NULL;
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_rfq_events_status') THEN
    ALTER TABLE rfq_events ADD CONSTRAINT ck_rfq_events_status
      CHECK (status IN ('open', 'closed', 'awarded', 'cancelled'));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_rfq_responses_values') THEN
    ALTER TABLE rfq_responses ADD CONSTRAINT ck_rfq_responses_values CHECK (
      total_inr >= 0 AND total_inr <> 'NaN'::numeric
      AND (support_rating IS NULL OR support_rating BETWEEN 1 AND 5)
      AND source IN ('manual', 'quote'));
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS goods_receipts (
  id UUID PRIMARY KEY,
  request_id UUID NOT NULL REFERENCES purchase_requests(id),
  lines JSONB NOT NULL,                     -- [{"line_no", "quantity", "asset_tags": [...]}]
  received_by VARCHAR(255) NOT NULL,
  received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_goods_receipts_request ON goods_receipts (request_id);

ALTER TABLE purchase_requests ADD COLUMN IF NOT EXISTS sourcing_flags JSONB;
ALTER TABLE purchase_requests ADD COLUMN IF NOT EXISTS rfq_id UUID REFERENCES rfq_events(id);

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_purchase_requests_status')
     AND NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_purchase_requests_status'
                     AND pg_get_constraintdef(oid) LIKE '%partially_received%') THEN
    ALTER TABLE purchase_requests DROP CONSTRAINT ck_purchase_requests_status;
    ALTER TABLE purchase_requests ADD CONSTRAINT ck_purchase_requests_status CHECK (status IN (
      'pending_approval', 'pending_grace_period', 'backordered', 'approved', 'ordered', 'partially_received',
      'fulfilled', 'partially_invoiced', 'invoice_received', 'rejected', 'cancelled', 'split'));
  END IF;
END $$;

-- Feature expansion Phase 4 (docs/feature-expansion-plan.md): TDS worked out
-- when an invoice is booked, and MSME payment deadlines. New table and
-- nullable columns only.
--
-- TDS sections, seeded with the rates and thresholds current in October 2026
-- (section codes as commonly known from the Income-tax Act, 1961). Finance
-- edits them on the GST and TDS page; a chartered accountant must confirm
-- them before use.
CREATE TABLE IF NOT EXISTS tds_sections (
  section VARCHAR(12) PRIMARY KEY,
  description TEXT NOT NULL,
  rate_pct NUMERIC(5, 2) NOT NULL,              -- vendor with a PAN
  rate_no_pan_pct NUMERIC(5, 2) NOT NULL,       -- vendor without one (higher rate)
  threshold_single_inr NUMERIC(14, 2),          -- TDS when one invoice is above this...
  threshold_annual_inr NUMERIC(14, 2),          -- ...or the year's total with the vendor is
  above_threshold_only BOOLEAN NOT NULL DEFAULT false,  -- only on the part above the annual threshold
  active BOOLEAN NOT NULL DEFAULT true,
  updated_by VARCHAR(255),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_tds_sections_values') THEN
    ALTER TABLE tds_sections ADD CONSTRAINT ck_tds_sections_values CHECK (
      rate_pct BETWEEN 0 AND 40 AND rate_no_pan_pct BETWEEN 0 AND 40
      AND (threshold_single_inr IS NULL OR threshold_single_inr >= 0)
      AND (threshold_annual_inr IS NULL OR threshold_annual_inr >= 0));
  END IF;
END $$;
INSERT INTO tds_sections (section, description, rate_pct, rate_no_pan_pct, threshold_single_inr, threshold_annual_inr, above_threshold_only) VALUES
  ('194C', 'Work contracts, e.g. installation or cabling by a company or firm', 2, 20, 30000, 100000, false),
  ('194J(a)', 'Fees for technical services, e.g. IT support, implementation, SaaS', 2, 20, NULL, 50000, false),
  ('194J(b)', 'Fees for professional services and royalty, e.g. software licences', 10, 20, NULL, 50000, false),
  ('194Q', 'Purchase of goods, e.g. hardware (buyer turnover above 10 crore)', 0.1, 5, NULL, 5000000, true)
ON CONFLICT (section) DO NOTHING;

ALTER TABLE invoice_matches ADD COLUMN IF NOT EXISTS invoice_date DATE;
ALTER TABLE invoice_matches ADD COLUMN IF NOT EXISTS taxable_value NUMERIC(14, 2);
ALTER TABLE invoice_matches ADD COLUMN IF NOT EXISTS gst_amount NUMERIC(14, 2);
ALTER TABLE invoice_matches ADD COLUMN IF NOT EXISTS tds_section VARCHAR(12);
ALTER TABLE invoice_matches ADD COLUMN IF NOT EXISTS tds_rate_pct NUMERIC(5, 2);
ALTER TABLE invoice_matches ADD COLUMN IF NOT EXISTS tds_base NUMERIC(14, 2);
ALTER TABLE invoice_matches ADD COLUMN IF NOT EXISTS tds_amount NUMERIC(14, 2);
ALTER TABLE invoice_matches ADD COLUMN IF NOT EXISTS net_payable NUMERIC(14, 2);
ALTER TABLE invoice_matches ADD COLUMN IF NOT EXISTS tds_notes JSONB;
-- Paid outside the platform (money moves only at the bank): recorded so the
-- MSME deadline list clears.
ALTER TABLE invoice_matches ADD COLUMN IF NOT EXISTS paid_at TIMESTAMPTZ;
ALTER TABLE invoice_matches ADD COLUMN IF NOT EXISTS paid_by VARCHAR(255);

-- Vendor tax profile (document-vendor-agent's migration 0012 adds the same
-- columns; whichever service starts first creates them).
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS pan VARCHAR(10);
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS tds_section VARCHAR(12);
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS ldc_rate_pct NUMERIC(5, 2);
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS ldc_valid_until DATE;
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS msme_udyam_number VARCHAR(19);
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS msme_category VARCHAR(10);
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS annual_turnover_inr NUMERIC(16, 2);

-- The approver the requester picked for the manager level (one of the people
-- assigned to dept_manager). NULL = anyone assigned to the level may decide.
ALTER TABLE purchase_requests ADD COLUMN IF NOT EXISTS selected_approver VARCHAR(255);
