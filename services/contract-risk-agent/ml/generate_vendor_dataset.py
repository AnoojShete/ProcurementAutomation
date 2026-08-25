#!/usr/bin/env python3
"""Builds the vendor risk-model training set.

Provenance:
  Primary source: the Kaggle "Procurement KPI Analysis Dataset" (real
  supplier performance/compliance data). If a cleaned copy is present at
  data/reference/procurement-kpi-analysis.csv (produced by the team's
  shared dataset-cleaning step — see data/README.md), this script maps its
  on-time-delivery and compliance-adjacent columns onto our feature space.

  Supplement: that dataset has no breach-disclosure, certification, or
  geographic-risk columns, and no ground-truth "incident" label, so those
  are generated synthetically with documented, reproducible logic (see
  `_synthesize_supplement` and `_synthesize_label` below) rather than
  invented with no rationale. If the Kaggle CSV isn't available in this
  environment, the whole dataset falls back to the same synthetic
  generator, seeded, so results are reproducible either way.

Run:
  python ml/generate_vendor_dataset.py
Writes:
  data/synthetic-vendors/vendor_risk_training_data.csv
"""
import os
import numpy as np
import pandas as pd

SEED = 42
N_SYNTHETIC = 400


def _find_data_dir() -> str:
    """Locate the repo's data/ directory. On the host this file sits at
    services/contract-risk-agent/ml/, three levels under the repo root. But
    the Docker image (see Dockerfile) copies this folder to /app/ml/,
    flattening that nesting — walking up three levels there would escape
    the container filesystem entirely. Walk upward looking for an actual
    `data/` sibling instead of assuming a fixed depth, and fall back to a
    local `data/` next to this script (e.g. /app/data/ in the container)
    if none is found."""
    here = os.path.dirname(os.path.abspath(__file__))
    candidate_root = here
    for _ in range(5):
        data_dir = os.path.join(candidate_root, "data")
        if os.path.isdir(data_dir):
            return data_dir
        parent = os.path.dirname(candidate_root)
        if parent == candidate_root:  # reached filesystem root
            break
        candidate_root = parent
    return os.path.join(here, "data")


DATA_DIR = _find_data_dir()
KAGGLE_CSV = os.path.join(DATA_DIR, "reference", "procurement-kpi-analysis.csv")
OUT_DIR = os.path.join(DATA_DIR, "synthetic-vendors")
OUT_CSV = os.path.join(OUT_DIR, "vendor_risk_training_data.csv")

FEATURE_COLUMNS = [
    "vendor_tenure_months",
    "on_time_delivery_rate",
    "financial_stability_score",
    "breach_disclosure_count",
    "security_cert_flag",
    "geo_risk_flag",
]
LABEL_COLUMN = "incident_occurred"


def _synthesize_supplement(n: int, rng: np.random.Generator) -> pd.DataFrame:
    """breach_disclosure_count / security_cert_flag / geo_risk_flag: not
    present in the Kaggle KPI dataset, so generated with a plausible
    real-world distribution (most vendors: zero breaches, no cert; a
    minority: certified and/or flagged geography)."""
    return pd.DataFrame(
        {
            "breach_disclosure_count": rng.poisson(0.3, n).clip(0, 6),
            "security_cert_flag": rng.random(n) < 0.35,
            "geo_risk_flag": rng.random(n) < 0.2,
        }
    )


def _synthesize_label(df: pd.DataFrame, rng: np.random.Generator) -> pd.Series:
    """Ground-truth 'did this vendor have an incident' doesn't exist in any
    public dataset either, so it's derived from a weighted rule over the
    features plus noise — an explainable proxy, not a claim of real
    incident history. Weights favor delivery/financial performance and
    breach history, matching how a procurement team would actually reason
    about vendor risk."""
    risk_signal = (
        (1 - df["on_time_delivery_rate"]) * 0.35
        + (1 - df["financial_stability_score"]) * 0.25
        + (df["breach_disclosure_count"] / 6.0).clip(0, 1) * 0.25
        + df["geo_risk_flag"].astype(float) * 0.1
        - df["security_cert_flag"].astype(float) * 0.1
        - (df["vendor_tenure_months"] / 120.0).clip(0, 1) * 0.1
    )
    noise = rng.normal(0, 0.08, len(df))
    prob = (risk_signal + noise).clip(0, 1)
    return (rng.random(len(df)) < prob).astype(int)


def _load_from_kaggle(rng: np.random.Generator) -> pd.DataFrame | None:
    if not os.path.exists(KAGGLE_CSV):
        return None
    raw = pd.read_csv(KAGGLE_CSV)
    # Column names vary by Kaggle export; map defensively.
    cols = {c.lower().strip(): c for c in raw.columns}

    def pick(*names, default=None):
        for n in names:
            if n in cols:
                return raw[cols[n]]
        return pd.Series([default] * len(raw))

    df = pd.DataFrame()
    df["vendor_tenure_months"] = pick("tenure_months", "vendor_tenure", default=24).fillna(24)
    otd = pick("on_time_delivery_rate", "on_time_rate", "delivery_compliance", default=0.8)
    # normalize to 0-1 if it looks like a percentage
    df["on_time_delivery_rate"] = otd.apply(lambda v: v / 100.0 if v > 1 else v).fillna(0.8)
    fin = pick("quality_rating", "compliance_score", "defect_rate", default=0.7)
    df["financial_stability_score"] = fin.apply(lambda v: v / 100.0 if v > 1 else v).fillna(0.7)

    supplement = _synthesize_supplement(len(df), rng)
    df = pd.concat([df.reset_index(drop=True), supplement.reset_index(drop=True)], axis=1)
    return df


def build_dataset() -> pd.DataFrame:
    rng = np.random.default_rng(SEED)
    df = _load_from_kaggle(rng)
    if df is None:
        # Fully-synthetic fallback (no Kaggle CSV present in this environment).
        df = pd.DataFrame(
            {
                "vendor_tenure_months": rng.integers(1, 120, N_SYNTHETIC),
                "on_time_delivery_rate": rng.beta(6, 2, N_SYNTHETIC),
                "financial_stability_score": rng.beta(5, 3, N_SYNTHETIC),
            }
        )
        supplement = _synthesize_supplement(N_SYNTHETIC, rng)
        df = pd.concat([df, supplement], axis=1)

    df["security_cert_flag"] = df["security_cert_flag"].astype(int)
    df["geo_risk_flag"] = df["geo_risk_flag"].astype(int)
    df[LABEL_COLUMN] = _synthesize_label(df, rng)
    return df[FEATURE_COLUMNS + [LABEL_COLUMN]]


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    df = build_dataset()
    df.to_csv(OUT_CSV, index=False)
    print(f"Wrote {len(df)} rows to {OUT_CSV}")
    print(f"Kaggle seed used: {os.path.exists(KAGGLE_CSV)}")


if __name__ == "__main__":
    main()
