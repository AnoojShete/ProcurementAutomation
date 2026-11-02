# Data Subject Request (DSR) Procedure

> **DRAFT - requires legal review**  
> **Audience**: Platform Administrators, Privacy Officers, Compliance Team  
> **Standard Operating Procedure**: Handling Access, Rectification, Erasure, Restriction, and Objection Requests

---

## 1. Regulatory Context & Timelines
Under GDPR (Art. 15-22), UK GDPR, and India DPDP Act 2023 (Section 11-14), individuals ("Data Subjects" / "Data Principals") have enforceable rights regarding their personal data.
- **Statutory Due Date**: Enforced by rule `privacy.dsr_days = 30` (30 calendar days from verified receipt).
- **Identity Verification**: No data may be exported or modified until the applicant's identity is positively confirmed (`identity_verified_by` field).

---

## 2. Request Lifecycle & Table Schema

Requests are managed in `privacy_requests`:
- `id`: Unique UUID.
- `type`: `access` | `rectification` | `erasure` | `restriction` | `objection`.
- `subject_email_hash`: SHA-256 hash of the requester's normalized lowercase email.
- `identity_verified_by`: Name or email of the compliance officer who confirmed government ID or corporate credentials.
- `received_at`: Exact timestamp of receipt.
- `due_at`: Calculated automatically (`received_at + interval '30 days'`).
- `status`: `pending` | `in_progress` | `completed` | `rejected`.
- `handler`: Assigned administrator.
- `outcome` & `outcome_reason`: Final determination and documentation.

---

## 3. Standard Operating Procedures by Request Type

### 3.1 Right of Access (Data Portability Export)
1. Navigate to **Control Panel -> Privacy -> Data Subject Requests**.
2. Select the verified request and click **"Generate Export"** (`POST /admin/privacy/requests/{id}/export`).
3. The platform collects all records linked to the individual across:
   - `auth_users`: Account metadata and profiles.
   - `vendors`: Contact records and tax profiles.
   - `notification_log`: Notifications addressed to the email.
   - `risk_scores` & `risk_score_reviews`: Any ratings authored by the user.
   - `vendor_evidence`: Evidence documents uploaded or verified by the user.
   - `audit_log`: Audit actions performed by the user's UUID.
4. An encrypted ZIP archive containing machine-readable JSON files is delivered to the administrator for secure transmission to the requester.

### 3.2 Right to Erasure ("Right to be Forgotten") & Separation of Duties
To prevent rogue deletion or destruction of audit trails, erasure strictly requires **Two-Admin Approval**:
1. First Administrator initiates the erasure proposal in the UI (`POST /admin/privacy/requests/{id}/erase`).
2. A second Administrator must log in, review the request, and confirm the action.
3. Upon dual confirmation:
   - The user's name and email in `auth_users` and `vendors` are replaced with `erased:<sha256_prefix>`.
   - Optional fields (`contact_phone`, `address`, `theme`) are set to `NULL`.
   - Primary key UUIDs are preserved to maintain foreign-key integrity in purchase requests, contracts, and audit trails.
   - The SHA-256 hash of the email is added to `email_suppressions` (`reason='erased'`) to prevent accidental re-import or re-contact.
   - Statutory records under active financial or tax retention are partially refused, with the specific statutory justification recorded in `outcome_reason`.

### 3.3 Right to Restriction & Objection
- **Objection**: When a vendor contact objects to processing, the address is added to `email_suppressions` (`reason='objection'`), blocking non-essential communications. A high-priority task is automatically generated for procurement to contact the vendor and nominate a replacement contact person.
- **Restriction**: The user account is flagged as restricted (`is_restricted = true`), pausing all automated email dispatches except mandatory security alerts.
