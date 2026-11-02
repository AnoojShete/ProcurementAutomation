# Personal Data Inventory & Data Mapping

> **DRAFT - requires legal review**  
> **Classification**: Internal Governance Artifact  
> **Last Verified**: November 2026

This inventory documents all locations where Personal Data (PII / Personally Identifiable Information) is collected, stored, processed, or transmitted across the platform's services and external integrations.

---

## 1. Inventory Summary Matrix

| Location / Store | Fields Containing Personal Data | Business & Processing Purpose | Authorized Access (Who Can Read It) | Current Retention Policy | Underlying Storage Location |
|---|---|---|---|---|---|
| **1. User Accounts** | `email`, `display_name`, `hashed_password`, `role`, `theme`, `last_login_at`, `password_changed_at` | Authentication, authorization, session management, and routing approvals to employees. | User themselves, platform administrators (`auth-service`). | Until account deactivation + 84 months statutory audit hold. | PostgreSQL: `auth_users` table in `auth-service`. |
| **2. Vendor Contacts** | `contact_email`, `contact_phone`, `address`, `pan`, `msme_udyam_number`, `annual_turnover_inr` | Vendor communications, RFQ issuance, purchase order dispatch, tax reporting (TDS/GST). | Buyers, approvers, finance officers, admins. | Duration of vendor commercial relationship + 7 years statutory tax retention. | PostgreSQL: `vendors` table in `document-vendor-agent` (shared DB). |
| **3. Notification Logs** | `recipient` (email), `template_name`, `subject`, `variable_hash` (body is NULL by default), `sent_at`, `error` | Delivery confirmation, troubleshooting dispatch failures, and spam/compliance audit trail. | Admins, compliance reviewers (`notification-agent`). | 12 months (`privacy.retention_notification_log_months`). | PostgreSQL: `notification_log` table in `notification-agent`. |
| **4. SMTP Configuration** | `email_from`, `username`, `password` (AES-256-GCM encrypted), `host`, `port` | Authenticating outbound operational email delivery via company mail server. | System administrators (`notification-agent`). | Active configuration lifespan; updated on demand. | PostgreSQL: `company_smtp_settings` table in `notification-agent`. |
| **5. Email Approval Tokens** | `approver_id`, `token_hash`, `used_ip`, `used_user_agent`, `used_at`, `used_action` | One-click email approval link validation, replay prevention, and non-repudiation audit trail. | Approvers (via link), system administrators (`approval-inventory-agent`). | 12 months (`privacy.retention_email_action_records_months`). IP truncated to `/24` and user-agent dropped. | PostgreSQL: `email_action_tokens` table in `approval-inventory-agent`. |
| **6. Audit Log Records** | `entity_id`, `entity_type`, `action`, `payload` (holds user UUIDs; email patterns scrubbed) | Non-repudiation, tamper-evident audit trail of financial and approval decisions. | Auditors, finance officers, compliance administrators. | 84 months (7 years; `privacy.audit_retention_months`). | PostgreSQL: `audit_log` table (shared DB). |
| **7. Ratings & Comments** | `requested_by` (user ID), reviewer feedback comments, risk flags, approval justifications | Documenting vendor performance, procurement decisions, and inherent risk clearance. | Buyers, approvers, finance officers, risk reviewers. | 36 months (`privacy.retention_rating_comment_months`). | PostgreSQL: `risk_scores`, `risk_score_reviews`, `approval_history` tables. |
| **8. Evidence Uploads** | `verified_by`, `notes`, uploaded compliance certificates, financial reports | Evidence verifying vendor certifications (ISO 27001, SOC 2, tax certificates). | Compliance reviewers, risk officers, auditors. | Duration of contract validity + 36 months. | PostgreSQL: `vendor_evidence` table & MinIO object storage bucket (`documents`). |
| **9. Raw API Responses** | Legal registrant names, proprietor names, filing status, API request parameters | Independent verification of vendor GSTIN, MSME, and sanctions status. | Compliance officers, automated risk scoring engine. | 24 months (`privacy.retention_raw_response_months`). | PostgreSQL: `vendor_signal_raw_responses` table in `contract-risk-agent`. |
| **10. Mailpit (Dev Catcher)** | Complete email messages (headers, recipient, body, links) sent in development environment | Local inspection and developer testing of outbound emails; no external egress. | Developers accessing `localhost:8025`. | Cleared on docker container recreation (`EMAIL_MODE=dev`). | Transient local memory / container storage in `mailpit` container. |
| **11. External Email Providers** | Recipient email, sender display name, operational message content, message IDs | Outbound transmission of transactional and operational notices to users/vendors. | External SMTP infrastructure (Gmail, SendGrid, Amazon SES, company mail exchange). | Controlled by provider's DPA and retention policies (typically 30-90 days transient). | External provider server infrastructure. |

---

## 2. Field-Level Classification Reference

| Field Name | Category | Classification | Special Restrictions |
|---|---|---|---|
| `email` / `recipient` / `contact_email` | Direct Identifier | Personal | Forbidden from subject lines (`privacy.no_personal_data_in_subject`); checked against `email_suppressions`. |
| `display_name` / `name` | Direct Identifier | Personal | Replaced with `erased:<hash>` upon approved erasure request. |
| `contact_phone` | Direct Identifier | Personal | Encrypted or restricted; optional field. |
| `used_ip` | Online Identifier | Personal | Anonymized to `/24` prefix past retention period. |
| `used_user_agent` | Device Identifier | Internal | Truncated/dropped past retention period. |
| `bank_account_number` | Financial Data | **RESTRICTED** | Strictly blocked from email templates at save and render. |
| `ifsc` | Financial Data | **RESTRICTED** | Strictly blocked from email templates at save and render. |
| `pan` | National Tax ID | **RESTRICTED** | Strictly blocked from email templates at save and render. |
| `password` / `hashed_password` | Credential | **RESTRICTED** | Never rendered, never logged, excluded from email templates. |
| `raw_api_data` / tokens | Technical / Telemetry | **RESTRICTED** | Never rendered in emails; single-use approval links use token hashes only. |
