# Approval & Inventory Intelligence Agent

This service handles purchase approvals, inventory locking, and license utilisation
tracking as part of the IT procurement platform. License reclaim decisions are driven
by a trained IsolationForest anomaly model with SHAP-attributed explanations.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check endpoint |
| POST | `/requests` | Create a new purchase/reclaim request |
| GET | `/requests/{request_id}` | Get request details and approval history |
| POST | `/requests/{request_id}/approve` | Approver approves a request |
| POST | `/requests/{request_id}/reject` | Approver rejects a request |
| GET | `/inventory` | Hardware + license inventory (with `anomaly_score` per license) |
| GET | `/inventory/licenses/{license_id}/usage-anomaly` | ML anomaly score + SHAP top factors |
| GET | `/inbox/{approver_id}` | Pending approvals routed to this approver |
| GET | `/metrics` | Prometheus metrics |

## Kafka Events Published

| Topic | When |
|-------|------|
| `approval.requested` | Every new purchase/reclaim request |
| `approval.decided` | Every approve/reject/escalation decision |
| `license.usage.updated` | Every scan cycle — now includes `anomaly_score`, `top_factors`, `model_version` |

## Kafka Events Consumed

| Topic | Source | Action |
|-------|--------|--------|
| `document.classified` | document-vendor-agent | Logged for audit |
| `contract.signed` | contract-risk-agent | Mark purchase_request `fulfilled`; activate license row |

**Note:** `license.usage.updated` is **published** by this service, not consumed.
Consuming your own output would be an infinite loop. The input to the usage pipeline
is raw SSO login data (see **License Utilisation Pipeline** below), not the Kafka event.

---

## Usage Anomaly Detection (ML)

### Why ML instead of a flat threshold?

The old approach flagged any license below 30 % utilisation. This created false positives
for licenses with normal weekend quiet — a team that logs in heavily Monday–Friday but
not at all Saturday/Sunday would look "underutilised" on a Sunday scan.

The IsolationForest model is trained **unsupervised** on 9 engineered features per license.
It learns that weekend dips, moderate seasonal variation, and steady-high weekday usage
are all **inlier** patterns. Genuine decline (gradual drop-off, sudden abandonment) becomes
an anomaly because it is isolated quickly by the ensemble of random trees.

### Features

| Feature | Description |
|---------|-------------|
| `active_seats_7d` | Distinct active users in last 7 days |
| `active_seats_30d` | Distinct active users in last 30 days |
| `active_seats_90d` | Distinct active users in last 90 days |
| `utilisation_ratio` | `active_seats_30d / total_seats` |
| `dod_rate_change` | Mean day-over-day Δ in daily logins (30d window) |
| `wow_rate_change` | Mean week-over-week Δ in weekly totals (90d window) |
| `variance_daily_logins` | Variance of daily login count over 90 days |
| `days_since_last_login` | Days since any seat last logged in |
| `weekend_ratio` | Fraction of logins on Sat/Sun — the model learns this is normal |

### Score interpretation

| `anomaly_score` | Interpretation |
|-----------------|----------------|
| 0.0 – 0.4 | Normal usage — no action |
| 0.4 – 0.6 | Mildly unusual — logged but no reclaim |
| > 0.6 | Anomalous → automatic reclaim request created |

Threshold is configurable: `config.yaml → utilisation.anomaly_threshold` (default 0.6).

### SHAP explainability

Every `anomaly_score` is accompanied by `top_factors` — the top 2–3 SHAP contributors
computed by `shap.TreeExplainer`:

```json
{
  "anomaly_score": 0.78,
  "top_factors": [
    {"feature": "dod_rate_change",       "contribution":  0.31},
    {"feature": "days_since_last_login", "contribution":  0.18},
    {"feature": "active_seats_30d",      "contribution": -0.09}
  ]
}
```

Positive `contribution` → feature pushes toward anomaly.  
Negative `contribution` → feature pushes toward inlier / normal.

This matches the `{feature, contribution}` shape already used by `risk.score.updated`.

### Training the model

```bash
# 1. Generate 60-90 days of daily history (4 usage patterns)
python scripts/generate_sso_logs.py
# Output: data/synthetic-sso-logs/sso_login_events.json

# 2. Engineer per-license features
cd services/approval-inventory-agent
python ml/generate_usage_dataset.py
# Output: ml/artifacts/usage_features.csv

# 3. Train IsolationForest and log to MLflow
python ml/train_usage_anomaly_model.py
# Output: ml/artifacts/model.joblib
#         ml/artifacts/model_version.txt
#         ml/artifacts/baseline_distribution.json
# MLflow: experiment 'usage_anomaly_detector' at http://mlflow:5000
```

### MLflow runs

MLflow experiment: **`usage_anomaly_detector`**  
Tracking UI: [http://localhost:5000](http://localhost:5000) (or `APP_MLFLOW_TRACKING_URI` env var)

Each run logs:
- **Params**: `n_estimators`, `contamination`, `max_samples`, `features`, `n_licenses_trained`
- **Metrics**: `mean_anomaly_score`, `max_anomaly_score`, `shap_available`
- **Artifacts**: `model.joblib`, `baseline_distribution.json`

The vendor risk model (`contract-risk-agent`) uses the same MLflow server under the
**`vendor_risk_classifier`** experiment.

---

## License Utilisation Pipeline

```
scripts/generate_sso_logs.py          (4 patterns, 60-90 days daily history)
      ↓  writes
data/synthetic-sso-logs/sso_login_events.json
      ↓  read by (every hour)
app/usage_scanner.py
      ↓
app/services/usage_service.py
      ├─→ license_usage table (DB upsert)
      ├─→ app/ml/usage_anomaly.py  (IsolationForest + SHAP)
      │        ↓
      │   anomaly_score + top_factors
      ├─→ license.usage.updated (Kafka, with anomaly fields)
      └─→ reclaim PurchaseRequest (if anomaly_score > 0.6)
```

---

## How to Run in Isolation

```bash
docker compose -f docker-compose.yml -f docker-compose.override.yml up approval-inventory-agent --build
```

## How to Run Tests

```bash
cd services/approval-inventory-agent
python -m pytest tests/ -v
```

| Test file | Coverage |
|-----------|----------|
| `test_spend_tier.py` | 8 boundary tests for tier routing |
| `test_redis_lock.py` | 5 tests including race-condition simulation |
| `test_usage_reclaim.py` | 6 tests for legacy flat-threshold logic (kept) |
| `test_event_schemas.py` | 6 tests validating Kafka event shapes |
| `test_contract_signed.py` | 5 tests for contract.signed handler |
| `test_usage_anomaly.py` | **5 tests** — steady/drop-off/weekend-dip proof + shape contract |

## Configuration

Spend tiers and approval chains are configurable via `config.yaml`. The current logic defines:
- Auto-approve: <= ₹500
- Manager approval: > ₹500 and <= ₹5000
- Manager + Finance approval: > ₹5000

Anomaly threshold: `config.yaml → utilisation.anomaly_threshold` (default 0.6)
