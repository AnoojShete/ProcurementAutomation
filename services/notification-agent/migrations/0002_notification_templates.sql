-- Notification templates edited from the Control Panel (app/services/template_store.py).
-- A row overrides the built-in app/templates/<name>.j2 with the same name,
-- or (is_custom) is a template that only exists here, sent through
-- notification.send. No row = the built-in file is used. Deleting a row
-- restores the built-in.
CREATE TABLE IF NOT EXISTS notification_templates (
    name             VARCHAR(100) PRIMARY KEY,
    description      TEXT NOT NULL DEFAULT '',
    subject          TEXT NOT NULL,
    body             TEXT NOT NULL,
    -- Comma-separated addresses that get a copy, besides the routed recipient.
    extra_recipients TEXT NOT NULL DEFAULT '',
    enabled          BOOLEAN NOT NULL DEFAULT TRUE,
    is_custom        BOOLEAN NOT NULL DEFAULT FALSE,
    updated_by       VARCHAR(255),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
