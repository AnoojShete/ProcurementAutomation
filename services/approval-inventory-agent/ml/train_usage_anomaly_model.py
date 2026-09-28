#!/usr/bin/env python3
"""
Train the license usage anomaly model and log the run to MLflow.

Algorithm: sklearn.ensemble.IsolationForest (unsupervised).

  Inlier population  → normal_steady + seasonal_weekend_dip licenses
                       (consistent logins, predictable weekend dip)
  Outlier signals    → gradual_decline + sudden_drop_off licenses
                       (IsolationForest assigns them negative raw scores)

Score mapping:
  IsolationForest.score_samples() returns negative values; more negative =
  more anomalous. We map to [0, 1] where 1 = maximally anomalous:
    anomaly_score = 1 - (raw_score - min_possible) / (max_possible - min_possible)
  In practice we normalise within the training distribution and clamp to [0, 1].

Explainability:
  shap.TreeExplainer(model) computes per-instance SHAP values at training time.
  The top_factors format matches risk.score.updated:
    [{"feature": "dod_rate_change", "contribution": -0.12}, ...]
  Positive contribution → feature pushes toward anomaly.
  Negative contribution → feature pushes toward inlier / normal.

Run:
  python ml/train_usage_anomaly_model.py
Writes:
  ml/artifacts/model.joblib        — {model, features, score_min, score_max}
  ml/artifacts/model_version.txt   — vYYYYMMDDHHMMSS
  ml/artifacts/baseline_distribution.json — score histogram for drift checks
"""
import json
import os
import sys
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
from generate_usage_dataset import build_features, FEATURE_COLUMNS, OUT_CSV, main as generate_main

ARTIFACT_DIR = os.path.join(_HERE, "artifacts")
MODEL_PATH    = os.path.join(ARTIFACT_DIR, "model.joblib")
VERSION_PATH  = os.path.join(ARTIFACT_DIR, "model_version.txt")
BASELINE_PATH = os.path.join(ARTIFACT_DIR, "baseline_distribution.json")

# IsolationForest hyper-parameters
N_ESTIMATORS  = 200
MAX_SAMPLES   = "auto"
CONTAMINATION = 0.2   # ~20 % of our licenses are anomalous (decline/drop-off)
RANDOM_STATE  = 42


def _try_mlflow():
    try:
        import mlflow
        return mlflow
    except ImportError:
        return None


def _normalise_scores(raw_scores: np.ndarray) -> tuple[np.ndarray, float, float]:
    """Map IsolationForest raw scores to [0, 1] (1 = most anomalous).

    raw_scores are negative; more negative = more anomalous.
    We flip and normalise: anomaly_score = (max - raw) / (max - min).
    Returns (normalised, score_min, score_max) so the runtime scorer can
    reproduce the same transformation.
    """
    s_min = float(raw_scores.min())
    s_max = float(raw_scores.max())
    span = s_max - s_min
    if span < 1e-9:
        return np.zeros_like(raw_scores), s_min, s_max
    normalised = (s_max - raw_scores) / span
    return np.clip(normalised, 0.0, 1.0), s_min, s_max


def train():
    os.makedirs(ARTIFACT_DIR, exist_ok=True)

    # ── Load / generate features ─────────────────────────────────────────────
    if not os.path.exists(OUT_CSV):
        print("Feature CSV not found — running generate_usage_dataset.py first…")
        generate_main()

    df = pd.read_csv(OUT_CSV)
    if df.empty or not all(c in df.columns for c in FEATURE_COLUMNS):
        print("Feature CSV missing expected columns — regenerating…")
        generate_main()
        df = pd.read_csv(OUT_CSV)

    app_names = df["app_name"].tolist()
    X = df[FEATURE_COLUMNS].values.astype(float)

    print(f"Training IsolationForest on {len(X)} license samples, {len(FEATURE_COLUMNS)} features…")

    # ── Train ────────────────────────────────────────────────────────────────
    from sklearn.ensemble import IsolationForest
    model = IsolationForest(
        n_estimators=N_ESTIMATORS,
        max_samples=MAX_SAMPLES,
        contamination=CONTAMINATION,
        random_state=RANDOM_STATE,
        n_jobs=-1,
    )
    model.fit(X)

    raw_scores = model.score_samples(X)           # negative; more negative = anomalous
    norm_scores, s_min, s_max = _normalise_scores(raw_scores)

    # ── SHAP values (training-time, for the baseline explainer check) ────────
    # shap.TreeExplainer supports IsolationForest natively.
    try:
        import shap
        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(X)    # (n_samples, n_features)
        shap_ok = True
        print(f"SHAP values computed: shape {shap_values.shape}")
    except Exception as e:
        print(f"SHAP computation failed (will still save model): {e}")
        shap_values = np.zeros_like(X)
        shap_ok = False

    # Print a per-license summary for inspection
    print(f"\n{'App name':30s} {'anomaly_score':>14s}  {'top factor':>25s}")
    print("-" * 75)
    for i, app in enumerate(app_names):
        score = norm_scores[i]
        sv = shap_values[i]
        top_idx = int(np.argmax(np.abs(sv)))
        top_feat = FEATURE_COLUMNS[top_idx] if shap_ok else "n/a"
        print(f"  {app:28s}  {score:.4f}        {top_feat}")

    # ── Save artifacts ───────────────────────────────────────────────────────
    version = datetime.now(timezone.utc).strftime("v%Y%m%d%H%M%S")

    artifact_bundle = {
        "model": model,
        "features": FEATURE_COLUMNS,
        "score_min": s_min,
        "score_max": s_max,
        "version": version,
    }
    if shap_ok:
        artifact_bundle["shap_explainer"] = shap.TreeExplainer(model)

    joblib.dump(artifact_bundle, MODEL_PATH)
    with open(VERSION_PATH, "w") as f:
        f.write(version)

    # Baseline distribution for drift monitoring (mirrors the risk model pattern)
    bins = np.linspace(0, 1, 11)
    hist, _ = np.histogram(norm_scores, bins=bins)
    baseline = {
        "version": version,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "bin_edges": bins.tolist(),
        "counts": hist.tolist(),
        "n_samples": int(len(norm_scores)),
        "contamination": CONTAMINATION,
        "feature_columns": FEATURE_COLUMNS,
    }
    with open(BASELINE_PATH, "w") as f:
        json.dump(baseline, f, indent=2)

    # ── MLflow logging ───────────────────────────────────────────────────────
    mlflow = _try_mlflow()
    if mlflow is not None:
        try:
            mlflow.set_tracking_uri(
                os.environ.get("APP_MLFLOW_TRACKING_URI", "http://mlflow:5000")
            )
            mlflow.set_experiment("usage_anomaly_detector")
            with mlflow.start_run(run_name=version):
                # Params
                mlflow.log_param("n_estimators", N_ESTIMATORS)
                mlflow.log_param("contamination", CONTAMINATION)
                mlflow.log_param("max_samples", MAX_SAMPLES)
                mlflow.log_param("features", FEATURE_COLUMNS)
                mlflow.log_param("n_licenses_trained", len(X))
                # Metrics
                mlflow.log_metric("mean_anomaly_score", float(np.mean(norm_scores)))
                mlflow.log_metric("max_anomaly_score", float(np.max(norm_scores)))
                mlflow.log_metric("shap_available", int(shap_ok))
                # Artifacts
                mlflow.log_artifact(MODEL_PATH)
                mlflow.log_artifact(BASELINE_PATH)
                mlflow.set_tag("model_version", version)
            print(f"\nMLflow run logged under experiment 'usage_anomaly_detector' — {version}")
        except Exception as e:
            print(f"MLflow logging skipped (tracking server unreachable): {e}")
    else:
        print("mlflow not installed — skipping tracking (install with: pip install mlflow)")

    print(f"\nTrained {version}: {len(X)} licenses, scores in [{norm_scores.min():.3f}, {norm_scores.max():.3f}]")
    return version


if __name__ == "__main__":
    train()
