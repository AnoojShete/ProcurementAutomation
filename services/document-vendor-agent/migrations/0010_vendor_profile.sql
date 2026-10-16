-- BR-4 vendor onboarding: contact and profile fields on the shared vendors
-- table. approval-inventory-agent adds the same columns; IF NOT EXISTS
-- (same types) keeps start-up order irrelevant.
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS contact_email VARCHAR(255);
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS contact_phone VARCHAR(50);
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS address TEXT;
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS category VARCHAR(100);
