-- Custom Company SMTP configuration (managed by admin only).
-- If configured and is_active = 1, outgoing emails are sent using these credentials.
-- If not configured or is_active = 0, system falls back to default mailer settings.
CREATE TABLE IF NOT EXISTS company_smtp_settings (
    comp_id INTEGER PRIMARY KEY DEFAULT 1,
    host VARCHAR(255) NOT NULL,
    port INTEGER NOT NULL DEFAULT 587,
    email_from VARCHAR(255) NOT NULL,
    username VARCHAR(255) NOT NULL,
    password TEXT NOT NULL,
    enable_ssl BOOLEAN NOT NULL DEFAULT TRUE,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
