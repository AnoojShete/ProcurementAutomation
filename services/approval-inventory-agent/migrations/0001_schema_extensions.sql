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
