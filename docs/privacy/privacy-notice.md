# Privacy Notice (Draft for Users & Vendor Contacts)

> **DRAFT - requires legal review**  
> **Notice**: This notice explains how the automated procurement platform processes personal data of employees, approvers, and vendor representatives. Qualified legal counsel must review and adapt this draft to local entity registration and statutory requirements.

---

## 1. Who We Are and What This Notice Covers
This Privacy Notice applies to data processed by the Enterprise IT Procurement Platform ("the Platform"). We act as a **Data Controller** (under GDPR / UK GDPR) and **Data Fiduciary** (under India DPDP Act 2023) for employee account data, and process business contact information of authorized vendor representatives for contract execution and purchase operations.

## 2. Personal Data We Collect
We collect and process only the minimal personal data strictly necessary for operational B2B procurement:
1. **Internal Users (Employees, Approvers, Buyers, Finance Staff)**:
   - Business email address, full name / display name.
   - Authentication credentials (passwords stored as cryptographic hashes).
   - Activity records: approval decisions, comments, request submissions, and login audit timestamps.
2. **Vendor Contacts & Representatives**:
   - Authorized representative name, business email address, and business telephone number.
   - Company physical address.
   - Tax identifiers associated with enterprise sole proprietorships or partnerships (e.g. PAN, GSTIN).
   - Electronic signature telemetry (IP address and timestamp) when signing contracts via our digital signing frame.

## 3. Why We Process Your Data (Lawful Bases)
We process personal data strictly under valid lawful bases:
- **Performance of a Contract**: Fulfilling procurement orders, processing invoices, executing supplier contracts, and issuing purchase requests.
- **Legal Obligation**: Complying with tax deductions at source (TDS), statutory audit retention, and GST invoicing laws.
- **Legitimate Interests**: Securing our internal systems against fraud, maintaining non-repudiable audit logs, preventing duplicate payments, and evaluating supplier delivery risk.

**We never send marketing, advertising, or promotional messages. We never sell, rent, or monetize your personal data.**

## 4. Operational Communications & Preference Management
The Platform sends only operational B2B notifications:
- **Transactional Notices & Security Alerts**: Cannot be opted out of, as they are essential to contract execution, security, and financial approvals.
- **Digest Summaries & Action Reminders**: Contain an automated **one-click unsubscribe link** (RFC 8058 compliant) and a link to configure digest frequencies.
- **Anti-Tracking Guarantee**: Our operational emails contain no remote tracking pixels, no click redirects, and no remote third-party scripts.

## 5. Data Retention & Minimisation
Personal data is retained only for as long as required to fulfill the operational purpose and comply with statutory retention mandates:
- **Email Notification Logs**: 12 months (email bodies are not stored).
- **Email Action Records**: 12 months (IP addresses truncated to `/24` and user agents removed).
- **Approval & Financial Records**: 84 months (7 years) pursuant to statutory tax and financial audit rules.
- **Risk Evaluation Notes**: 36 months.
Automated retention purges run daily to permanently remove or pseudonymise expired data.

## 6. Your Rights (Data Subject Requests)
Subject to applicable laws (GDPR, UK GDPR, DPDP Act 2023), you have the right to:
- **Access**: Request a copy of all personal data held about you in machine-readable JSON format.
- **Rectification**: Request correction of inaccurate or incomplete contact details.
- **Erasure ("Right to be Forgotten")**: Request deletion of your personal data where retention is no longer justified. Where statutory retention applies, records are pseudonymised (`erased:<hash>`) and audit references preserved.
- **Restriction & Objection**: Object to non-essential communications or restrict processing during dispute.

To exercise any right, contact our Data Protection Team at: **`privacy@procurement.local`**.  
Requests are fulfilled free of charge within **30 days** (or the statutory deadline for your region).
