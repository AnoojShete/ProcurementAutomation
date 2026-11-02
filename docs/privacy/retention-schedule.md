# Platform Personal Data Retention Schedule

> **DRAFT - requires legal review**  
> **Governance Policy**: Technical Data Minimisation and Retention  
> **Last Updated**: November 2026

---

## 1. Statutory Foundations & Default Rules
Under GDPR Article 5(1)(e), UK GDPR, and India DPDP Act Section 8(7), personal data must not be kept longer than is strictly necessary for the purposes for which it is processed. Furthermore, statutory tax retention (e.g. Section 128 Indian Companies Act / Section 44AB Income Tax Act / UK Companies Act 2006) mandates retaining financial records for 6 to 8 years.

Every retention parameter in this system is codified as a **Business Rule** in category `privacy`. Every rule enforces minimum and maximum boundaries and requires a documented audit justification to alter.

---

## 2. Retention Schedule Table

| Record Type | Database Table / Asset | Retention Period (Rule Key) | Hard Min / Max Allowed | Post-Retention Purge Action | Statutory / Business Justification |
|---|---|---|---|---|---|
| **Notification Delivery Logs** | `notification_log` | 12 months (`privacy.retention_notification_log_months`) | 1 - 60 months | Hard delete expired rows. | Dispute resolution and delivery verification. |
| **Email Message Bodies** | `notification_log.body` | **0 months** (`privacy.store_email_bodies=false`) | Always False | Bodies not stored; template ID, recipient, and variable hash stored only. | Data minimisation by design. |
| **Email Action Token Records** | `email_action_tokens` | 12 months (`privacy.retention_email_action_records_months`) | 1 - 60 months | Truncate `used_ip` to `/24` subnet, drop `used_user_agent`, hash token. | Non-repudiation of approvals. |
| **Risk Score Comments & Reviews** | `risk_scores`, `risk_score_reviews` | 36 months (`privacy.retention_rating_comment_months`) | 6 - 120 months | Anonymize reviewer identifiers; remove review commentary. | Vendor performance trend analysis. |
| **Raw Third-Party Signal Responses** | `vendor_signal_raw_responses` | 24 months (`privacy.retention_raw_response_months`) | 1 - 60 months | Delete raw API responses beyond `retention_until` date. | Verification of initial vendor registration. |
| **Financial Audit Log Payloads** | `audit_log` | 84 months (7 years; `privacy.audit_retention_months`) | 12 - 120 months | Retain immutable transaction IDs; scrub email addresses. | Statutory accounting and tax compliance. |
| **Data Subject Requests (DSR)** | `privacy_requests` | 36 months | 12 - 60 months | Retained for supervisory authority inspection. | Accountability and proof of compliance. |

---

## 3. Automated Temporal Purge Engine
- A dedicated background Temporal workflow (`DailyPrivacyPurgeWorkflow`) executes every 24 hours at 02:00 UTC.
- The purge job evaluates timestamps against the configured retention limits.
- **Legal Hold Override**: Records associated with entities flagged with active legal holds (`legal_hold = true`) or statutory holds are skipped.
- **Audit Logging**: The purge engine appends a summary row to the audit register recording counts of purged records only, never personal identifiers.
