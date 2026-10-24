-- Prompt 10: Bulk approval batches, email batch tokens, and request user ID ownership

CREATE TABLE IF NOT EXISTS email_batch_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    token_hash TEXT UNIQUE NOT NULL,
    approver_id TEXT NOT NULL,
    request_ids JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ,
    used_ip TEXT,
    used_user_agent TEXT,
    revoked_at TIMESTAMPTZ,
    revoked_reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_email_batch_tokens_hash ON email_batch_tokens (token_hash);
CREATE INDEX IF NOT EXISTS idx_email_batch_tokens_approver ON email_batch_tokens (approver_id);

CREATE TABLE IF NOT EXISTS approval_batches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    approver_id TEXT NOT NULL,
    approver_role TEXT NOT NULL,
    channel TEXT NOT NULL DEFAULT 'portal',
    email_batch_token_id UUID REFERENCES email_batch_tokens(id) ON DELETE SET NULL,
    idempotency_key TEXT NOT NULL,
    requested_ids JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'executing',
    count_requested INTEGER NOT NULL DEFAULT 0,
    count_approved INTEGER NOT NULL DEFAULT 0,
    count_skipped INTEGER NOT NULL DEFAULT 0,
    total_approved_amount NUMERIC(12, 2) NOT NULL DEFAULT 0,
    rules_snapshot JSONB,
    ip TEXT,
    user_agent TEXT,
    acknowledged_auto_sign BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    CONSTRAINT uq_approval_batches_approver_idem UNIQUE (approver_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_approval_batches_approver ON approval_batches (approver_id, created_at DESC);

CREATE TABLE IF NOT EXISTS approval_batch_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id UUID NOT NULL REFERENCES approval_batches(id) ON DELETE CASCADE,
    request_id UUID NOT NULL REFERENCES purchase_requests(id) ON DELETE CASCADE,
    step_index INTEGER NOT NULL,
    result TEXT NOT NULL, -- approved, skipped, failed
    reason_code TEXT,
    decision_id UUID,
    decided_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_approval_batch_items_batch ON approval_batch_items (batch_id);

-- Ownership via user ID (Section 6.3)
ALTER TABLE purchase_requests ADD COLUMN IF NOT EXISTS requested_by_user_id TEXT;
CREATE INDEX IF NOT EXISTS idx_purchase_requests_user_id ON purchase_requests (requested_by_user_id);

ALTER TABLE purchase_requests ADD COLUMN IF NOT EXISTS source TEXT DEFAULT 'manual';
ALTER TABLE purchase_requests ADD COLUMN IF NOT EXISTS source_ref TEXT;
