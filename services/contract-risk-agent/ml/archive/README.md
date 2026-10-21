# Retired ML Vendor Risk Classifier & Drift Service

These files have been retired from vendor risk scoring as part of Prompt 9B:
- `train_risk_model.py` (legacy GradientBoostingClassifier)
- `evaluate_risk_model.py` (model evaluation script)
- `generate_vendor_dataset.py` (synthetic dataset generator)
- `redteam_profiles.json` (model test profiles)
- `drift_service.py` (PSI drift monitoring)

## Retirement Reason
Vendor risk scoring has been migrated to a 100% deterministic, transparent, integer point-based (0–100) scorecard defined by versioned business rules. ML models, SHAP explanations, EBMs, and PSI drift monitoring are retired from the vendor risk path.

Note: The license-usage anomaly model (`approval-inventory-agent/ml`, IsolationForest + SHAP) is a completely separate feature and remains active.

## Status (21 Oct 2026)
The copies that still sat in `ml/` were removed, and the image no longer trains
the model. These files are a record of the evaluation in
`docs/results/risk-model.json`; `evaluate_risk_model.py` imported helpers from
`risk_service.py` that were removed with the ML path, so it no longer runs.
`generate_vendor_dataset.py` is still used: `ml/evaluate_scorecard.py` scores
its test split with the deterministic ruleset (ROC-AUC 0.738 vs 0.715 for the
retired forest; `docs/results/risk-scorecard-eval.json`). The red-team set
for the scorecard is `ml/redteam_scorecard.py`.
