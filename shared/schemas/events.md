# Event Schema Contract

This is the single source of truth for every Kafka event in the platform.
If you publish a topic, your producer must match this exactly. If you
consume a topic, your consumer must read exactly these keys.

## Event envelope

Every message on every topic is wrapped the same way:

```json
{
  "event_id": "uuid",
  "event_type": "document.classified",
  "timestamp": "2026-08-22T10:15:00Z",
  "source_service": "document-vendor-agent",
  "payload": { }
}
```

- `event_id` — a fresh UUID per message (not the entity's own id).
- `event_type` — matches the Kafka topic name.
- `timestamp` — ISO-8601 UTC.
- `source_service` — the service name that published the event.
- `payload` — defined per-topic below.

## Topics and payloads

| Topic | Published by | Consumed by | `payload` fields |
|---|---|---|---|
| `document.ingested` | document-vendor-agent | document-vendor-agent (worker) | `document_id` (uuid), `uploaded_by` (string), `file_type` (`pdf`\|`image`), `minio_path` (string), `uploaded_at` (iso8601) |
| `document.classified` | document-vendor-agent | approval-inventory-agent, notification-agent | `document_id`, `document_type` (`po`\|`invoice`\|`quote`), `vendor_name_raw` (string), `extracted_fields` (object: `line_items[]`, `total`, `currency`, `document_number`, `document_date`), `confidence_scores` (object, field→0-1 float), `overall_confidence` (0-1 float), `needs_review` (bool) |
| `vendor.matched` | document-vendor-agent | contract-risk-agent | `document_id`, `vendor_id` (uuid), `vendor_name_normalized` (string), `match_type` (`existing`\|`new`), `match_confidence` (0-1 float) |
| `license.usage.updated` | approval-inventory-agent | notification-agent | `license_id` (uuid), `vendor_id` (uuid), `app_name` (string), `total_seats` (int), `active_seats_30d`/`60d`/`90d` (int), `utilisation_score` (0-1 float), `period_end` (iso8601), **`anomaly_score`** (0-1 float — 0 normal, 1 maximally anomalous; IsolationForest), **`top_factors`** (array of `{feature (string), contribution (float)}` sorted by \|SHAP\|; positive contribution = pushes toward anomaly, negative = toward inlier; top 2-3 features), **`model_version`** (string — training run id, e.g. `v20260902123456`). `anomaly_score`/`top_factors`/`model_version` are **additive** — consumers that ignore unknown fields remain unaffected. |
| `approval.requested` | approval-inventory-agent | notification-agent | `request_id` (uuid), `request_type` (`hardware`\|`license`\|`saas`\|`reclaim`), `requested_by` (string), `department` (string), `amount` (number), `currency` (string, default `"INR"`), `spend_tier` (`auto`\|`manager`\|`manager+finance`), `approval_chain` (array of approver ids in order), `sla_deadline` (iso8601) |
| `approval.decided` | approval-inventory-agent | contract-risk-agent, notification-agent | `request_id`, `decision` (`approved`\|`rejected`), `decided_by` (string), `decision_level` (string), `escalated` (bool), `decided_at` (iso8601), `comments` (string, nullable) |
| `contract.generated` | contract-risk-agent | notification-agent | `contract_id` (uuid), `purchase_request_id` (uuid), `vendor_id` (uuid), `template_used` (string), `version` (int), `status` (`draft`\|`pending_signature`), `generated_at` (iso8601) |
| `contract.signed` | contract-risk-agent | notification-agent, approval-inventory-agent | `contract_id`, `signed_at` (iso8601), `signed_by` (string), `esign_provider_ref` (string) |
| `contract.renewal.due` | contract-risk-agent | notification-agent | `contract_id`, `vendor_id`, `renewal_type` (`auto`\|`manual`), `notice_period_days` (int), `contract_end_date` (iso8601 date), `days_remaining` (int), `alert_level` (`60`\|`30`\|`15`) |
| `risk.score.updated` | contract-risk-agent | notification-agent | `vendor_id`, `risk_band` (`Low`\|`Medium`\|`High`), `risk_score` (0-1 float), `top_factors` (array of `{feature, contribution}`), `model_version` (string), `scored_at` (iso8601) |
| `vendor.offboarded` | contract-risk-agent | notification-agent | `vendor_id`, `offboarded_by` (string), `offboarded_at` (iso8601), `contracts_flagged` (array of contract ids flagged for final reconciliation), `data_retention_flag` (bool) |
| `vendor.payment_details_flagged` | document-vendor-agent | notification-agent | `vendor_id`, `change_request_id` (uuid), `submitted_by` (string), `source` (`portal`\|`email_derived_document`\|`api`), `fields_changed` (array of field names, e.g. `bank_account_number`), `flagged_at` (iso8601) — never carries the raw bank/routing values, only that a change happened |
| `notification.send` | any service (generic fallback) | notification-agent | `recipient` (string, email or user id), `channel` (`email`\|`slack`), `template_name` (string), `template_context` (object), `priority` (`urgent`\|`digest`), `related_entity_id` (string) |

If your service publishes a topic, write a **producer** that matches this
shape exactly. If you consume a topic, write your **consumer** to read
exactly these keys — don't guess at field names from the architecture
diagram, use this table.

## REST response envelope

Standard success: `{"data": {...}, "meta": {}}`.
Standard error: `{"error": {"code": "string", "message": "string"}}` with an
appropriate HTTP status.

All ids are UUID strings. All money fields are plain decimal numbers plus a
separate `currency` field. All timestamps are ISO-8601 UTC.
