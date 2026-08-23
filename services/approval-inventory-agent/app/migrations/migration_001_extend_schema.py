"""
Alembic migration: Extend the shared schema with all columns required
by the approval-inventory-agent.

The shared init.sql creates minimal tables. This migration adds the
full column set each table needs for this service's features:
  - purchase_requests: request_type, vendor_id, spend_tier, approval_chain,
                       current_approver_index, sla_deadline, items, 
                       backorder_parent_id, is_backordered, comments, updated_at,
                       document_id
  - approval_history:  Full approval decision table (new)
  - licenses:          cost_per_seat, currency, period_start, period_end,
                       status, updated_at
  - license_usage:     Per-user license usage tracking (new)
  - inventory:         Hardware inventory with stock levels (new)
  - vendors:           Extended columns: name_normalized, contact_email,
                       contact_phone, address, category, status, updated_at
  - audit_log:         Align columns to ORM model (entity_type, entity_id,
                       action, performed_by, details)

Run this migration with:
    cd services/approval-inventory-agent
    python -m app.migrations.run_migration
"""
import asyncio
import logging
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from app.config import settings

logger = logging.getLogger(__name__)

MIGRATION_SQL = """
-- ============================================================
-- Migration: approval-inventory-agent schema extensions
-- Run AFTER shared/db/init.sql has been applied.
-- All statements use IF NOT EXISTS / IF EXISTS so this is idempotent.
-- ============================================================

-- 1. Extend vendors table
ALTER TABLE vendors
    ADD COLUMN IF NOT EXISTS name_normalized TEXT,
    ADD COLUMN IF NOT EXISTS contact_email TEXT,
    ADD COLUMN IF NOT EXISTS contact_phone TEXT,
    ADD COLUMN IF NOT EXISTS address TEXT,
    ADD COLUMN IF NOT EXISTS category TEXT,
    ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'active',
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;

-- 2. Extend purchase_requests table with all fields needed by approval service
ALTER TABLE purchase_requests
    ADD COLUMN IF NOT EXISTS request_type TEXT,
    ADD COLUMN IF NOT EXISTS vendor_id UUID REFERENCES vendors(id),
    ADD COLUMN IF NOT EXISTS document_id UUID REFERENCES documents(id),
    ADD COLUMN IF NOT EXISTS spend_tier TEXT,
    ADD COLUMN IF NOT EXISTS approval_chain JSONB,
    ADD COLUMN IF NOT EXISTS current_approver_index INT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS sla_deadline TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS items JSONB,
    ADD COLUMN IF NOT EXISTS backorder_parent_id UUID REFERENCES purchase_requests(id),
    ADD COLUMN IF NOT EXISTS is_backordered BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS comments TEXT,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;

-- 3. Create approval_history table (new — not in shared init.sql)
CREATE TABLE IF NOT EXISTS approval_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id UUID NOT NULL REFERENCES purchase_requests(id),
    decision TEXT NOT NULL,
    decided_by TEXT NOT NULL,
    decision_level TEXT,
    escalated BOOLEAN DEFAULT FALSE,
    comments TEXT,
    decided_at TIMESTAMPTZ DEFAULT now()
);

-- 4. Extend licenses table
ALTER TABLE licenses
    ADD COLUMN IF NOT EXISTS cost_per_seat NUMERIC(10,2),
    ADD COLUMN IF NOT EXISTS currency TEXT DEFAULT 'INR',
    ADD COLUMN IF NOT EXISTS period_start DATE,
    ADD COLUMN IF NOT EXISTS period_end DATE,
    ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'active',
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;

-- 5. Create license_usage table (new — not in shared init.sql)
CREATE TABLE IF NOT EXISTS license_usage (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    license_id UUID NOT NULL REFERENCES licenses(id),
    user_email TEXT NOT NULL,
    last_login_at TIMESTAMPTZ,
    login_count_30d INT DEFAULT 0,
    login_count_60d INT DEFAULT 0,
    login_count_90d INT DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(license_id, user_email)
);

-- 6. Create inventory table (new — not in shared init.sql)
CREATE TABLE IF NOT EXISTS inventory (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sku TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    category TEXT,
    total_quantity INT NOT NULL DEFAULT 0,
    available_quantity INT NOT NULL DEFAULT 0,
    reserved_quantity INT NOT NULL DEFAULT 0,
    unit_cost NUMERIC(10,2),
    currency TEXT DEFAULT 'INR',
    location TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- 7. Fix audit_log to match ORM model columns
-- The shared init.sql uses 'payload' but the ORM uses 'details' and 'performed_by'
ALTER TABLE audit_log
    ADD COLUMN IF NOT EXISTS entity_type TEXT,
    ADD COLUMN IF NOT EXISTS performed_by TEXT,
    ADD COLUMN IF NOT EXISTS details JSONB;

-- Index for fast inbox queries
CREATE INDEX IF NOT EXISTS idx_purchase_requests_status
    ON purchase_requests(status);
CREATE INDEX IF NOT EXISTS idx_purchase_requests_vendor_id
    ON purchase_requests(vendor_id);
CREATE INDEX IF NOT EXISTS idx_approval_history_request_id
    ON approval_history(request_id);
CREATE INDEX IF NOT EXISTS idx_license_usage_license_id
    ON license_usage(license_id);
CREATE INDEX IF NOT EXISTS idx_inventory_sku
    ON inventory(sku);
"""


async def run_migration():
    """Apply the approval-inventory-agent schema migration."""
    engine = create_async_engine(settings.database_url, echo=True)
    async with engine.begin() as conn:
        logger.info("Applying approval-inventory-agent schema migration...")
        await conn.execute(text(MIGRATION_SQL))
        logger.info("Migration applied successfully.")
    await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_migration())
