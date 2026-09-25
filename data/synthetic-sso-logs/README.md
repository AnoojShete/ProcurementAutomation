# Synthetic SSO Login Events — Data Generation Guide

## Overview

`data/synthetic-sso-logs/sso_login_events.json` is produced by
`scripts/generate_sso_logs.py`. It provides 60–90 days of per-seat, per-day
SSO login history across eight software licenses. The IsolationForest anomaly
detector in `services/approval-inventory-agent/ml/` is trained on features
derived from this data.

All randomness is seeded (`random.Random(42)`) so the output is **fully
reproducible** across runs and CI environments.

---

## Event Schema

Each event is a JSON object:

```json
{
  "app_name":        "Microsoft 365 E3",
  "user_email":      "user001@example.com",
  "login_timestamp": "2026-06-15T09:23:41+00:00"
}
```

| Field             | Type   | Description                              |
|-------------------|--------|------------------------------------------|
| `app_name`        | string | Must match an `app_name` in the licenses table |
| `user_email`      | string | Stable pool per license (user001–userN)  |
| `login_timestamp` | string | ISO-8601 UTC, timezone-aware             |

---

## Usage Patterns

The generator produces **four distinct patterns** to give the model a realistic
inlier/outlier distribution:

### 1. `normal_steady`
- **Licenses**: Microsoft 365 E3, Slack Business+
- **Behaviour**: 80–95 % of active seats log in on weekdays; 15–30 % on weekends.
- **Purpose**: Primary inlier class — what a healthy, well-utilised license looks like.
- **Should be flagged?** No.

### 2. `gradual_decline`
- **Licenses**: Zoom Pro, Salesforce Starter
- **Behaviour**: Usage starts at ~80 % of active seats and declines linearly to ~10 %
  by the most recent day. Weekend fraction is additionally reduced.
- **Purpose**: Outlier class — represents a slow bleed of adoption the model should catch.
- **Should be flagged?** Yes (high anomaly_score expected).

### 3. `sudden_drop_off`
- **Licenses**: Adobe Creative Cloud, Jira Software
- **Behaviour**: Normal weekday/weekend usage up to `drop_day` days ago, then
  near-zero (0–5 % residual) from that point forward.
  - Adobe CC: drop at ~62 days ago (≈ 30 d of inactivity at scoring time)
  - Jira Software: drop at ~55 days ago
- **Purpose**: Sharpest outlier — team stopped using the tool suddenly.
- **Should be flagged?** Yes.

### 4. `seasonal_weekend_dip`
- **Licenses**: GitHub Enterprise, Figma Professional
- **Behaviour**: Strong stable weekday usage (82–97 %); deliberate weekend quiet (10–20 %).
  The weekday line is consistent — there is no downward trend.
- **Purpose**: Tests that the model has learned weekend dips are **inlier behaviour**,
  not anomalies. The `weekend_ratio` feature captures this signal explicitly so
  IsolationForest can distinguish planned seasonal variation from genuine decline.
- **Should be flagged?** **No** — this is the key proof-test that the ML model
  beats the old flat-threshold approach (which would have flagged Monday-centric
  metrics if a weekend happened to be recent).

---

## Reproducing the Data

```bash
# From the repository root
python scripts/generate_sso_logs.py
# Output: data/synthetic-sso-logs/sso_login_events.json
```

The generator prints a summary table:

```
  Microsoft 365 E3               pattern=normal_steady      events=  5,234
  Slack Business+                pattern=normal_steady      events=  6,012
  Zoom Pro                       pattern=gradual_decline    events=  2,891
  ...
Wrote 28,XXX events to data/synthetic-sso-logs/sso_login_events.json
```

---

## Relationship to the ML Pipeline

```
scripts/generate_sso_logs.py
      ↓  writes
data/synthetic-sso-logs/sso_login_events.json
      ↓  read by
ml/generate_usage_dataset.py   →  ml/artifacts/usage_features.csv
      ↓  read by
ml/train_usage_anomaly_model.py
      ↓  writes
ml/artifacts/model.joblib
ml/artifacts/model_version.txt
      ↓  loaded at runtime by
app/ml/usage_anomaly.py        →  anomaly_score + top_factors (SHAP)
```

---

## Extending the Data

To add a new license pattern:

1. Add an entry to the `LICENSES` list in `scripts/generate_sso_logs.py`.
2. If it needs a new pattern type, add a `_day_login_count_<pattern>()` function.
3. Re-run `python scripts/generate_sso_logs.py` to regenerate the JSON.
4. Re-train the model: `python ml/train_usage_anomaly_model.py`.
