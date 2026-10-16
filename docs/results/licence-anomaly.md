# Licence-usage anomaly model — evaluation

Generated 2026-10-16T10:17:51+00:00 by `services/approval-inventory-agent/ml/evaluate_usage_anomaly.py`
on 600 simulated licences (seed 2026, 30 % with an anomalous pattern;
patterns in `ml/usage_population.py`). Split 360 / 120 / 120 train / validation / test.
Synthetic data: these numbers say the model separates the simulated patterns, not how it does on a real company's logins.

## Thresholds (chosen on validation, rules `license.anomaly_*`)

| Status | Score ≥ | Chosen as | On test: precision | recall | flagged |
|---|---|---|---|---|---|
| anomalous (reclaim proposed) | **0.39** | lowest score with precision ≥ 0.90 | 0.833 | 0.694 | 30 (5 false) |
| watch (shown for review) | **0.34** | highest score with recall ≥ 0.90 | 0.789 | 0.833 | 38 (8 false) |

## Test set

| | ROC-AUC | Average precision |
|---|---|---|
| **This model** (scale_free features, trained on 360 licences) | **0.954** | **0.873** |
| Original 9 features, trained on the same 360 licences | 0.849 | 0.744 |
| Previous model: original features, trained on 5 licences | 0.659 | 0.549 |
| Low utilisation alone (1 − utilisation) | 0.687 | 0.608 |

## Feature set (picked on validation by average precision)

| Set | Features | Validation AP | Validation ROC-AUC |
|---|---|---|---|
| original | active_seats_7d, active_seats_30d, active_seats_90d, utilisation_ratio, dod_rate_change, wow_rate_change, variance_daily_logins, days_since_last_login, weekend_ratio | 0.651 | 0.799 |
| **scale_free** | utilisation_7d, utilisation_ratio, utilisation_90d, retention_7d, retention_30d, days_since_last_login, weekend_ratio | 0.915 | 0.967 |
| retention | retention_7d, retention_30d, days_since_last_login | 0.88 | 0.951 |

## By pattern (test set)

| Pattern | Truth | Licences | Mean score | ≥ watch | ≥ anomalous |
|---|---|---|---|---|---|
| steady | normal | 46 | 0.12 | 9 % | 4 % |
| weekend dip | normal | 19 | 0.21 | 10 % | 5 % |
| low stable | normal | 19 | 0.29 | 10 % | 10 % |
| gradual decline | anomaly | 14 | 0.37 | 71 % | 36 % |
| sudden dropoff | anomaly | 15 | 0.51 | 87 % | 87 % |
| abandoned | anomaly | 7 | 0.75 | 100 % | 100 % |
