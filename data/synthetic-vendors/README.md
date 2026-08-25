# Vendor risk training data

`vendor_risk_training_data.csv` is the training set for the vendor risk
classifier in `services/contract-risk-agent`.

## Provenance

- **Primary source**: the Kaggle "Procurement KPI Analysis Dataset" (real
  supplier performance/compliance data). If a cleaned copy is placed at
  `data/reference/procurement-kpi-analysis.csv`, the generation script maps
  its on-time-delivery and compliance-adjacent columns onto this dataset's
  feature space instead of inventing them.
- **Supplement**: that dataset has no breach-disclosure count, security
  certification flag, geographic-risk flag, or ground-truth incident label —
  those are generated synthetically with documented, seeded logic (see
  `services/contract-risk-agent/ml/generate_vendor_dataset.py`), not
  invented arbitrarily.
- **Fallback**: this checked-in CSV was generated with no Kaggle CSV present
  in the build environment, so it's the fully-synthetic fallback path
  (`Kaggle seed used: False` when you re-run the script) — every feature is
  seeded (`SEED = 42`) and reproducible, but none of it is real supplier
  data. Drop a cleaned Kaggle export at `data/reference/procurement-kpi-analysis.csv`
  and re-run the script to regenerate this file seeded from real data.

## Regenerating

```
cd services/contract-risk-agent
python ml/generate_vendor_dataset.py
```

Training the model (`python ml/train_risk_model.py`) regenerates this file
automatically if it's missing.
