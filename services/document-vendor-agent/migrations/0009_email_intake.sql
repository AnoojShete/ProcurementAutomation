-- Where a document came from (BR-1): 'upload' (portal / API), 'folder'
-- (./inbox) or 'email', and for email the sender's address.
ALTER TABLE documents ADD COLUMN IF NOT EXISTS source TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_sender TEXT;

-- One row per email taken from the intake mailbox, so each message is
-- handled once (the mailbox itself is never modified) and rejected
-- attachments keep their reason.
CREATE TABLE IF NOT EXISTS email_intake (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  message_id TEXT NOT NULL UNIQUE,
  sender TEXT,
  subject TEXT,
  received_at TIMESTAMPTZ,
  processed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  status TEXT NOT NULL,                          -- processed | partial | rejected
  document_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
  rejections JSONB NOT NULL DEFAULT '[]'::jsonb  -- [{"filename", "reason"}]
);
CREATE INDEX IF NOT EXISTS idx_email_intake_processed ON email_intake (processed_at DESC);
