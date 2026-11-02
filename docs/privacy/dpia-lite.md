# Data Protection Impact Assessment Lite (DPIA-Lite)

> **DRAFT - requires legal review**  
> **Target Process**: Automated B2B Procurement Processing, Vendor Risk Scoring, and Automated Email Notifications  
> **Assessment Date**: November 2026

---

## 1. Description of Processing Operations
The platform automates the lifecycle of IT hardware and software procurement:
1. **Invoice & Document Ingestion**: Optical character recognition (OCR) and layout analysis extract vendor names, invoice figures, and bank details from uploaded PDFs.
2. **Deterministic Risk Scoring**: Vendor entities are scored against 100 points across 6 objective risk groups (corporate existence, certifications, delivery records, breach catalogue, financial stability, and contract terms).
3. **Approval Escalation**: Temporal workflows route purchase approvals to managers based on spend thresholds.
4. **Outbound Operational Notifications**: Alerts notify requesters, approvers, and vendors of milestone decisions.

---

## 2. Assessment of Necessity & Proportionality
- **Data Minimisation**: No consumer or sensitive category personal data (e.g. biometric, health, genetic, political) is processed. Processing is strictly limited to corporate B2B identity attributes and business contact information.
- **Purpose Limitation**: Personal data is solely utilized to process transactions, prevent payment fraud, and fulfill statutory tax deductions.
- **Body Minimisation in Notification Logs**: Email bodies are stripped before saving to database logs (`privacy.store_email_bodies=false`).
- **No Marketing**: The platform enforces a technical ban on marketing communications.

---

## 3. Risk Assessment & Mitigations

| Identified Risk | Severity | Likelihood | Technical Controls & Mitigations Built | Residual Risk |
|---|---|---|---|---|
| **Unauthorized access to financial data or bank credentials in templates** | High | Low | Restricted placeholders (`bank_account_number`, `ifsc`, `pan`) are blocked at both template save and render time. Only secured portal links are permitted. | **Low** |
| **Email header injection allowing spam relaying** | High | Low | Carriage returns (`\r`) and line feeds (`\n`) are stripped from all email headers. Maximum recipient caps enforced via business rules. | **Negligible** |
| **Exposure of personal data via open tracking or redirects** | Medium | Medium | Automated tests verify that no open-tracking pixels, click redirects, or remote images exist in any email template. | **Low** |
| **Cross-border transfer without adequate safeguards** | Medium | Low | Regional cross-border checks block non-essential emails and display warnings in Email Settings when an EU/EEA/UK recipient is mapped to an unapproved processor region. | **Low** |
| **Excessive retention of personal data** | Medium | Medium | Automated daily Temporal purge job enforces strict retention limits, truncates IP addresses to `/24`, and drops user-agent strings. | **Low** |
| **Improper erasure breaking financial audit trails** | High | Low | DSR erasure replaces PII with `erased:<hash>` while preserving foreign-key IDs and audit logs. A second administrator must approve every erasure request. | **Low** |

---

## 4. Conclusion & Sign-Off
The residual risks identified in this DPIA-Lite are within acceptable organizational risk tolerances, provided all automated technical controls and separation-of-duties workflows remain enabled.
