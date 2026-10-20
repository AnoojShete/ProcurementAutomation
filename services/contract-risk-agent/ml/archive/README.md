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
