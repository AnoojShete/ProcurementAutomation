-- Add configurable recipient field to notification_templates.
-- Null or empty = the default routed recipient for this event is used.
-- Jinja placeholders (e.g. {{ requester_email }}) or email addresses are supported.
ALTER TABLE notification_templates ADD COLUMN IF NOT EXISTS recipient TEXT;
