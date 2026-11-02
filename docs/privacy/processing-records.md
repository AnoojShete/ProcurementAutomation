# Record of Processing Activities (ROPA)

> **DRAFT - requires legal review**  
> **Regulatory Reference**: Article 30 GDPR / UK GDPR & Section 8 India DPDP Act 2023  
> **Entity**: Enterprise IT Procurement Platform  
> **Role**: Data Controller (Internal User Data) / Data Fiduciary / Data Processor (Vendor Contact Data)

---

## Processing Activities Register

| ID | Activity Name | Business Purpose | Data Categories | Data Subjects | Lawful Basis | Retention Rule Key | Recipients & Processors | Storage Location | Reviewed On |
|---|---|---|---|---|---|---|---|---|---|
| `ACT-01` | **User Authentication & Access Management** | Managing employee logins, credentials, session tokens, and role-based permissions. | Email, display name, password hash, role, token version, login timestamps. | `users` | `contract` (Employment contract / terms of service) | `privacy.audit_retention_months` | Internal `auth-service`, Redis session cache | PostgreSQL `auth_users` | 2026-11-01 |
| `ACT-02` | **Purchase Request Approval Workflow** | Routing spend approvals through multi-level managerial chains and recording decisions. | Request submitter ID, approver ID, approval comments, decision timestamp. | `users` | `legitimate_interest` (Corporate financial governance) | `privacy.audit_retention_months` | Internal approvers, Temporal workflow engine | PostgreSQL `purchase_requests`, `approval_history` | 2026-11-01 |
| `ACT-03` | **Single-Action Email Approval** | Enabling approvers to decide requests via cryptographic one-time action links in email. | Approver ID, token hash, IP address, user-agent, decision payload. | `users` | `legitimate_interest` (Operational efficiency) | `privacy.retention_email_action_records_months` | Internal approvers, email transport provider | PostgreSQL `email_action_tokens` | 2026-11-01 |
| `ACT-04` | **Vendor Onboarding & Due Diligence** | Registering new suppliers, verifying business existence, GST identity, and bank details. | Vendor contact email, phone, address, tax IDs (PAN, GSTIN), signatory name. | `vendor_contacts` | `contract` (Pre-contractual measures) | `privacy.retention_raw_response_months` | Procurement team, GST validation API | PostgreSQL `vendors`, `vendor_evidence` | 2026-11-01 |
| `ACT-05` | **Contract Generation & Electronic Signing** | Drafting procurement agreements and executing signatures via Documenso / DocuSign. | Signer name, business email, IP address, digital signature certificate. | `users`, `vendor_contacts` | `contract` (Contract execution & legal compliance) | `privacy.audit_retention_months` | Contract signatories, Documenso / DocuSign | PostgreSQL `contracts`, `contract_signers` | 2026-11-01 |
| `ACT-06` | **Operational Email Dispatch & Logging** | Sending transactional, reminder, and security notifications regarding procurement actions. | Recipient email address, template name, message subject, delivery status. | `users`, `vendor_contacts` | `contract` / `legitimate_interest` | `privacy.retention_notification_log_months` | Outbound SMTP provider (Company SMTP / SES / SendGrid) | PostgreSQL `notification_log` | 2026-11-01 |
| `ACT-07` | **Vendor Risk Assessment & Adverse Media** | Evaluating supplier risk bands, breach catalogue checks, and financial stability. | Vendor legal entity name, publicly reported breach records, evaluation notes. | `rated_people`, `vendor_contacts` | `legitimate_interest` (Enterprise risk management & anti-fraud) | `privacy.retention_rating_comment_months` | Risk officers, HIBP local catalogue, news APIs | PostgreSQL `risk_scores`, `risk_score_reviews` | 2026-11-01 |
| `ACT-08` | **Tax Compliance & TDS Deductions** | Verifying Lower Deduction Certificates (LDC), MSME status, and computing statutory withholding. | Vendor PAN, MSME Udyam number, annual turnover tier. | `vendor_contacts` | `legal_obligation` (Income Tax Act & GST Act) | `privacy.audit_retention_months` | Finance department, statutory tax authorities | PostgreSQL `vendors`, `gstr2b_uploads` | 2026-11-01 |

---

## Export & Auditing
- This processing register is maintained in database table `privacy_processing_records` and updated on every architectural revision.
- Administrators can export this register directly to CSV via `GET /admin/privacy/processing-records/export`.
- Cells starting with formula characters (`=`, `+`, `-`, `@`) are automatically escaped with a leading apostrophe to prevent CSV injection.
