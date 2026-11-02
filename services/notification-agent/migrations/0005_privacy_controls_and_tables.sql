-- Prompt 12B: Privacy controls for email and personal data (GDPR baseline, DPDP Act, UK GDPR)

-- 1. Extend notification_templates with governance attributes
ALTER TABLE notification_templates ADD COLUMN IF NOT EXISTS category VARCHAR(20) DEFAULT 'transactional';
ALTER TABLE notification_templates ADD COLUMN IF NOT EXISTS audience VARCHAR(20) DEFAULT 'internal';
ALTER TABLE notification_templates ADD COLUMN IF NOT EXISTS lawful_basis VARCHAR(50) DEFAULT 'contract';
ALTER TABLE notification_templates ADD COLUMN IF NOT EXISTS contains_personal_data BOOLEAN DEFAULT false;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_template_category') THEN
        ALTER TABLE notification_templates ADD CONSTRAINT ck_template_category
            CHECK (category IN ('transactional', 'security', 'reminder', 'digest'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_template_audience') THEN
        ALTER TABLE notification_templates ADD CONSTRAINT ck_template_audience
            CHECK (audience IN ('internal', 'requester', 'approver', 'vendor'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_template_lawful_basis') THEN
        ALTER TABLE notification_templates ADD CONSTRAINT ck_template_lawful_basis
            CHECK (lawful_basis IN ('contract', 'legitimate_interest', 'legal_obligation', 'consent'));
    END IF;
END $$;

-- 2. Placeholder classifications table
CREATE TABLE IF NOT EXISTS notification_placeholder_classes (
    name VARCHAR(64) PRIMARY KEY,
    classification VARCHAR(20) NOT NULL CHECK (classification IN ('public', 'internal', 'personal', 'restricted')),
    description TEXT
);

INSERT INTO notification_placeholder_classes (name, classification, description) VALUES
    ('bank_account_number', 'restricted', 'Supplier bank account number - barred from emails'),
    ('ifsc', 'restricted', 'Bank IFSC routing code - barred from emails'),
    ('pan', 'restricted', 'National Permanent Account Number - barred from emails'),
    ('password', 'restricted', 'User or account credential - barred from emails'),
    ('raw_api_data', 'restricted', 'Direct external API dump - barred from emails'),
    ('auth_token', 'restricted', 'Session or API token - barred from emails'),
    ('requested_by', 'personal', 'Name of request submitter - blocked from subjects'),
    ('recipient', 'personal', 'Target email or recipient name - blocked from subjects'),
    ('approver_name', 'personal', 'Name of assigned approver - blocked from subjects'),
    ('email', 'personal', 'User email address - blocked from subjects'),
    ('contact_name', 'personal', 'Vendor contact person - blocked from subjects'),
    ('request_id', 'internal', 'Unique purchase request reference'),
    ('amount', 'internal', 'Transaction amount'),
    ('currency', 'internal', 'Transaction currency'),
    ('department', 'internal', 'Corporate department'),
    ('vendor_name', 'internal', 'Vendor trading or legal name'),
    ('step_index', 'internal', 'Approval chain level index'),
    ('decision', 'internal', 'Approval decision string'),
    ('portal_url', 'public', 'Secure portal destination link'),
    ('privacy_notice_url', 'public', 'Public URL of privacy notice'),
    ('org_name', 'public', 'Corporate enterprise name')
ON CONFLICT (name) DO UPDATE SET
    classification = EXCLUDED.classification,
    description = EXCLUDED.description;

-- 3. Processing Activities Register (ROPA)
CREATE TABLE IF NOT EXISTS privacy_processing_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    activity TEXT NOT NULL,
    purpose TEXT NOT NULL,
    data_categories TEXT NOT NULL,
    data_subjects TEXT NOT NULL CHECK (data_subjects IN ('users', 'vendor_contacts', 'rated_people')),
    lawful_basis TEXT NOT NULL CHECK (lawful_basis IN ('contract', 'legitimate_interest', 'legal_obligation', 'consent')),
    retention_rule_key TEXT NOT NULL,
    recipients_processors TEXT NOT NULL,
    storage_location TEXT NOT NULL,
    reviewed_on TIMESTAMPTZ DEFAULT now()
);

INSERT INTO privacy_processing_records
    (activity, purpose, data_categories, data_subjects, lawful_basis, retention_rule_key, recipients_processors, storage_location)
VALUES
    ('User Authentication & Access', 'Managing employee accounts and role sessions', 'Email, display name, password hash, role', 'users', 'contract', 'privacy.audit_retention_months', 'auth-service, Redis', 'auth_users'),
    ('Spend Approval Routing', 'Routing spend requests through multi-level approval chains', 'Submitter ID, approver ID, comments, timestamps', 'users', 'legitimate_interest', 'privacy.audit_retention_months', 'Temporal, approval-inventory-agent', 'purchase_requests, approval_history'),
    ('Single-Action Email Approvals', 'One-click cryptographic decision links in email', 'Approver ID, token hash, IP, user agent', 'users', 'legitimate_interest', 'privacy.retention_email_action_records_months', 'email-action-tokens, SMTP transport', 'email_action_tokens'),
    ('Vendor Onboarding & Verification', 'Supplier profile creation, tax checks, bank validation', 'Contact email, phone, address, PAN, GSTIN', 'vendor_contacts', 'contract', 'privacy.retention_raw_response_months', 'document-vendor-agent, GST portal API', 'vendors, vendor_evidence'),
    ('Contract Generation & E-Signing', 'Drafting agreements and executing digital signatures', 'Signatory name, business email, signature cert', 'vendor_contacts', 'contract', 'privacy.audit_retention_months', 'contract-risk-agent, Documenso', 'contracts, contract_signers'),
    ('Operational Email Notifications', 'Delivering transactional notices and digest summaries', 'Recipient email, template name, delivery status', 'users', 'contract', 'privacy.retention_notification_log_months', 'notification-agent, Company SMTP', 'notification_log'),
    ('Vendor Risk Evaluation', 'Scoring supplier reliability and reviewing breaches', 'Vendor name, breach observations, rating notes', 'rated_people', 'legitimate_interest', 'privacy.retention_rating_comment_months', 'contract-risk-agent, HIBP database', 'risk_scores, risk_score_reviews')
ON CONFLICT DO NOTHING;

-- 4. Email suppressions table
CREATE TABLE IF NOT EXISTS email_suppressions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    address_hash VARCHAR(64) UNIQUE NOT NULL,
    scope VARCHAR(30) NOT NULL CHECK (scope IN ('non_essential', 'all_non_security')),
    reason VARCHAR(30) NOT NULL CHECK (reason IN ('bounce', 'complaint', 'objection', 'erased')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_email_suppressions_hash ON email_suppressions (address_hash);

-- 5. Data Subject Requests (DSR)
CREATE TABLE IF NOT EXISTS privacy_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type VARCHAR(20) NOT NULL CHECK (type IN ('access', 'rectification', 'erasure', 'restriction', 'objection')),
    subject_email_hash VARCHAR(64) NOT NULL,
    identity_verified_by VARCHAR(255) NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    due_at TIMESTAMPTZ NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'in_progress', 'completed', 'rejected')),
    handler VARCHAR(255),
    outcome VARCHAR(50),
    outcome_reason TEXT,
    second_admin_approver VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_privacy_requests_hash ON privacy_requests (subject_email_hash);
CREATE INDEX IF NOT EXISTS idx_privacy_requests_due ON privacy_requests (due_at, status);

-- 6. Sub-Processors & External Providers
CREATE TABLE IF NOT EXISTS data_processors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    purpose TEXT NOT NULL,
    country TEXT NOT NULL,
    dpa_reference TEXT,
    transfer_mechanism_note TEXT,
    added_by TEXT,
    reviewed_on TIMESTAMPTZ DEFAULT now()
);

INSERT INTO data_processors (name, purpose, country, dpa_reference, transfer_mechanism_note, added_by) VALUES
    ('Corporate SMTP Gateway', 'Outbound operational email relay', 'Internal', 'Internal Controller Infrastructure', 'Direct Internal Processing', 'system'),
    ('Documenso Frame', 'Embedded digital contract signing', 'DE', 'DPA-DOCUMENSO-2026', 'EU Standard Contractual Clauses', 'system'),
    ('Have I Been Pwned Offline', 'Breach dataset analysis', 'Internal', 'Creative Commons BY 4.0 Local Database', 'Offline local replica', 'system')
ON CONFLICT DO NOTHING;

-- 7. Privacy Incidents
CREATE TABLE IF NOT EXISTS privacy_incidents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    description TEXT NOT NULL,
    data_categories TEXT,
    subjects_affected_estimate INT DEFAULT 0,
    contained_at TIMESTAMPTZ,
    authority_notified_at TIMESTAMPTZ,
    individuals_notified_at TIMESTAMPTZ,
    notes TEXT
);
