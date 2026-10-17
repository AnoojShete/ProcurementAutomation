# Vendor risk model — evaluation

Generated 2026-10-15T16:24:08+00:00 by `services/contract-risk-agent/ml/evaluate_risk_model.py`.

## Dataset

- 2000 vendors (fully synthetic, seeded, 20% stressed-vendor segment); train 1600 / test 400, stratified.
- 360 with an incident (18.0%).
- Label: risk = 0.35·(1−on-time) + 0.25·(1−financial) + 0.25·min(breaches/6, 1) + 0.10·geo flag − 0.10·certified − 0.10·min(tenure/120, 1), plus N(0, 0.08) noise; incident drawn with that probability.
- Features: vendor_tenure_months, on_time_delivery_rate, financial_stability_score, breach_disclosure_count, security_cert_flag, geo_risk_flag.

## Results (test set)

| Metric | Value |
|---|---|
| Accuracy (threshold 0.5) | 0.72 |
| ROC-AUC | 0.715 |
| ROC-AUC with 20% of values missing | 0.726 |
| ROC-AUC ceiling (the label rule's own probability) | 0.739 |

| | Predicted no incident | Predicted incident |
|---|---|---|
| Actual no incident | 249 | 79 |
| Actual incident | 33 | 39 |

### Incident rate per band

| Band | Vendors | Incidents | Incident rate |
|---|---|---|---|
| Low | 153 | 10 | 0.065 |
| Medium | 185 | 37 | 0.2 |
| High | 62 | 25 | 0.403 |

### Feature importances

| Feature | Importance |
|---|---|
| on_time_delivery_rate | 0.349 |
| financial_stability_score | 0.21 |
| vendor_tenure_months | 0.207 |
| breach_disclosure_count | 0.091 |
| security_cert_flag | 0.08 |
| geo_risk_flag | 0.064 |

## Red-team profiles (12/12 as expected)

| Profile | Expected | Band | Score | Signals | Top factor | OK |
|---|---|---|---|---|---|---|
| Established, certified, reliable | Low | Low | 0.077 | 6/6 | on_time_delivery_rate | ✓ |
| Solid mid-size supplier | Low | Low | 0.173 | 6/6 | on_time_delivery_rate | ✓ |
| Good record, no certification | Low | Low | 0.153 | 6/6 | on_time_delivery_rate | ✓ |
| Late deliveries, weak finances | High | High | 0.739 | 6/6 | vendor_tenure_months | ✓ |
| Repeated breaches, flagged geography | High | High | 0.665 | 6/6 | breach_disclosure_count | ✓ |
| Everything bad | High | High | 0.758 | 6/6 | vendor_tenure_months | ✓ |
| New vendor, decent numbers | Medium | Medium | 0.421 | 6/6 | vendor_tenure_months | ✓ |
| Reliable but one breach and flagged geography | Medium | Medium | 0.453 | 6/6 | on_time_delivery_rate | ✓ |
| Perfect record but GSTIN cancelled (override) | High | High | 0.077 | 6/6 | override:gstin | ✓ |
| Nothing on file | not High | Medium | 0.437 | 0/6 | — | ✓ |
| Good partial record (delivery and finances unknown) | Low | Low | 0.156 | 4/6 | vendor_tenure_months | ✓ |
| Bad delivery known, rest unknown | not Low | Medium | 0.653 | 1/6 | on_time_delivery_rate | ✓ |
