-- Schema extensions this service's ORM models (app/models.py) require on
-- top of shared/db/init.sql. Never edit init.sql directly — this file is
-- applied idempotently (IF NOT EXISTS everywhere) at startup by
-- app/database.py's init_db(), the same raw-SQL-at-startup pattern
-- services/approval-inventory-agent/app/database.py uses.

CREATE TABLE IF NOT EXISTS notification_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  recipient VARCHAR(255) NOT NULL,
  channel VARCHAR(20) DEFAULT 'email',
  event_type VARCHAR(100) NOT NULL,
  template_name VARCHAR(100),
  subject VARCHAR(500),
  body TEXT,
  priority VARCHAR(20),
  related_entity_id VARCHAR(255),
  status VARCHAR(20) DEFAULT 'sent',
  error TEXT,
  sent_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_notification_log_recipient ON notification_log(recipient);
CREATE INDEX IF NOT EXISTS idx_notification_log_event_type ON notification_log(event_type);
CREATE INDEX IF NOT EXISTS idx_notification_log_created_at ON notification_log(created_at);

CREATE TABLE IF NOT EXISTS notification_digest_queue (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  recipient VARCHAR(255) NOT NULL,
  event_type VARCHAR(100) NOT NULL,
  template_name VARCHAR(100),
  template_context JSONB,
  related_entity_id VARCHAR(255),
  flushed BOOLEAN DEFAULT false,
  flushed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_digest_queue_recipient_flushed ON notification_digest_queue(recipient, flushed);
