-- Prompt 8: Email action tokens table for single-action email approvals
CREATE TABLE IF NOT EXISTS email_action_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    token_hash TEXT UNIQUE NOT NULL,
    request_id UUID NOT NULL REFERENCES purchase_requests(id) ON DELETE CASCADE,
    approver_id TEXT NOT NULL,
    step_index INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ,
    used_action TEXT,
    used_ip TEXT,
    used_user_agent TEXT,
    revoked_at TIMESTAMPTZ,
    revoked_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_email_action_tokens_token_hash ON email_action_tokens (token_hash);
CREATE INDEX IF NOT EXISTS idx_email_action_tokens_req_step ON email_action_tokens (request_id, step_index);
