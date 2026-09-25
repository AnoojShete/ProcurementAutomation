# Data Directory — PII & Data Retention Policy

## What lives here

This directory contains synthetic data used to bootstrap the platform for
development and demonstration:

| Subdirectory | Contents | PII-like fields |
|---|---|---|
| `synthetic-invoices/` | Sample PDF/image invoices for the document intake pipeline | Vendor names, invoice amounts, line items |
| `synthetic-vendors/` | Seed vendor records (names, risk attributes) | Vendor business names, GSTIN numbers (synthetic) |
| `synthetic-sso-logs/` | Simulated SSO login events for license utilisation | Usernames, timestamps |

All data is **entirely synthetic** — generated for this project, not sourced
from any real vendor, employee, or financial system.

## Runtime data (Postgres + MinIO)

Once the platform is running, the following services store PII or
commercially sensitive information in the shared Postgres instance and MinIO
object store:

| Service | Table / Bucket | Sensitive fields |
|---|---|---|
| document-vendor-agent | `documents`, MinIO `documents` bucket | Uploaded invoices/POs (may contain real vendor banking details in production use) |
| document-vendor-agent | `vendors` | Vendor names, GSTIN, normalised identifiers |
| document-vendor-agent | `vendor_payment_changes` | Change audit trail — which payment fields changed (field names only, never raw values) |
| approval-inventory-agent | `purchase_requests` | Requester names, department, spend amounts |
| contract-risk-agent | `contracts` | Generated contract text (may include vendor/buyer details) |
| notification-agent | `notification_log` | Recipient email addresses, email subjects/bodies |

## Retention policy

For this project's scope (academic demonstration), the following policy
applies:

1. **No automated deletion** is implemented. Data persists in Docker volumes
   until manually removed (`docker compose down -v`).

2. **Production recommendation**: if this platform were deployed with real
   data, implement:
   - Automated purge of `notification_log` rows older than 90 days
   - Automated purge of `notification_digest_queue` flushed rows older than
     30 days
   - MinIO lifecycle rules to expire uploaded documents after the configured
     retention period
   - Anonymisation or deletion of `vendor_payment_changes` audit records
     after the legal retention window (typically 7 years for financial
     records in India per the Companies Act)

3. **Right to erasure**: vendor offboarding (contract-risk-agent's
   `POST /vendors/{id}/offboard`) sets a `data_retention_flag` on the
   vendor record and publishes a `vendor.offboarded` event. In production,
   this flag would trigger a downstream data-cleanup workflow.

4. **Encryption at rest**: not configured for Docker-volume-backed Postgres
   in this demo environment. Production deployments should use encrypted
   storage volumes and TLS for all inter-service communication.
