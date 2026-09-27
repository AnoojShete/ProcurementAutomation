# approval-inventory-agent (port 8002)

Purchase requests and approvals, inventory, license utilisation and
reclaim, the invoice ledger, and the order monitor. Owner: Niraj
(controls added by Anjali, Sep 26). Every route except `/health` and
`/metrics` needs a JWT; role checks are in `app/api/*.py`.

## Endpoints (behind the gateway at `/api/...`)

| Prefix | Routes | Notes |
|---|---|---|
| `/requests` | `POST /`, `GET /`, `GET /search`, `GET /{id}`, `POST /{id}/approve`, `POST /{id}/reject`, `POST /{id}/decline-reclaim`, `GET /audit` | Requesters see only their own; identity comes from the JWT. Approve/reject signal a Temporal workflow, so the status changes a moment later. |
| `/inbox` | `GET /{approver_id}` | Takes an approver *role* from the approval chain (e.g. `dept_manager`), approver/finance/admin only. |
| `/inventory` | `GET /`, plus the license routes below | Hardware + licenses, with each license's stored anomaly score. |
| `/licenses` | `GET /anomaly-summary`, `GET /{id}/usage-history`, `GET /{id}/reclaim-history`, `GET /{id}/usage-anomaly`, `POST /{id}/mark-reviewed` | Same handlers are also mounted under `/inventory/licenses`. |
| `/authority` | `GET /`, `GET /check/{request_id}`, `POST/DELETE /assignments`, `POST/DELETE /delegations` | Who may approve which level, up to what amount; separation of duties. |
| `/invoices` | `POST /match`, `GET /ledger/{request_id}`, `GET /matches`, `POST /release-holds/{vendor_id}` | Three-way match ledger. Booking and releasing holds need the pipeline's service token; staff get dry-run. |
| `/orders` | `GET /summary/latest`, `GET /summary`, `POST /summary/run` | Order monitor summaries (staff/service only). |
| `/ops` | `GET /eventing`, `GET /dlq`, `POST /dlq/{id}/replay`, `POST /dlq/{id}/discard`, `POST /reconcile`, `POST /showcase/inject-out-of-order-event` | Outbox/DLQ state and repair; the showcase route only exists with showcase mode on. |

## Kafka

Publishes `approval.requested`, `approval.decided`, `license.usage.updated`,
`notification.send`, `order.summary.generated`.
Consumes `document.classified` (logged), `invoice.matched` (request →
`invoice_received` / `partially_invoiced`), `contract.signed` (request →
`fulfilled`, license activated), `business_rule.updated` (cache refresh).
Consumers run through `shared/eventing.deliver` (retry, then `event_dlq`).
Payloads: `shared/schemas/events.md`.

## Approvals

Spend tiers come from the business-rules engine (`approval.spend_tiers`,
editable on the admin Business Rules page); `config.yaml` is only the
fallback (≤ ₹500 auto, ≤ ₹5,000 manager, above that manager + finance).
Each request runs a Temporal `ApprovalWorkflow` that waits for a decision
per level and escalates after the SLA (`approval.sla_escalation_hours`,
fallback 48 h). A decision is only accepted from someone assigned to that
level (`approver_assignments`, or a delegation) who didn't raise the
request and hasn't approved another level of it
(`app/services/approval_authority.py`).

## License usage anomaly model

An IsolationForest (unsupervised) scores each license 0–1 from 9 features
computed from SSO login events; SHAP gives the top contributing features.

| Feature | Meaning |
|---|---|
| `active_seats_7d` / `_30d` / `_90d` | Distinct active users in the window |
| `utilisation_ratio` | `active_seats_30d / total_seats` |
| `dod_rate_change` | Mean day-over-day change in daily logins (30 d) |
| `wow_rate_change` | Mean week-over-week change (90 d) |
| `variance_daily_logins` | Variance of daily logins (90 d) |
| `days_since_last_login` | Days since any seat logged in |
| `weekend_ratio` | Share of logins on Sat/Sun |

Scores above `config.yaml → utilisation.anomaly_threshold` (0.6) create a
reclaim request with a grace period; declining a reclaim sets a cooldown
(`license.reclaim_cooldown_days`, default 45). A license with no SSO
history reports `insufficient_history`, not 0.

`app/usage_scanner.py` re-scores every `APP_USAGE_SCAN_INTERVAL_SECONDS`
(default 3600) and publishes `license.usage.updated`.

**Data and training.** The image ships
`data/synthetic-sso-logs/sso_login_events.json` (7,986 events, 5 licenses,
90 days) and trains the model at build time. That file was produced by
this service's `scripts/generate_sso_logs.py`. The repo-root
`scripts/generate_sso_logs.py` is a different, 8-license / 4-pattern
generator that is **not** what's committed (see
`data/synthetic-sso-logs/README.md`).

```bash
cd services/approval-inventory-agent
python ml/generate_usage_dataset.py       # → ml/artifacts/usage_features.csv
python ml/train_usage_anomaly_model.py    # → ml/artifacts/model.joblib (+ MLflow run)
```

MLflow experiment `usage_anomaly_detector`: http://localhost:5050 (the
container listens on 5000 inside the Docker network).

On the seeded data the ranking is questionable (a license at 76 %
utilisation scores as anomalous) — tracked in TODO.md.

## Tests

```bash
./scripts/test-service.sh approval-inventory-agent   # from the repo root
```

Covers spend tiers, Redis locks, reclaim logic, event schemas, the
anomaly model, license endpoints, approval authority, lifecycle
enforcement, the invoice ledger, the order monitor, metrics, approval
security, reclaim decline, and a guard against Temporal APIs missing from
temporalio 1.6.
