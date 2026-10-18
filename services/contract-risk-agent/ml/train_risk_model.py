#!/usr/bin/env python3
"""Trains the vendor risk classifier and logs the run to MLflow.

Run:
  python ml/train_risk_model.py
Writes:
  ml/artifacts/model.joblib
  ml/artifacts/model_version.txt
  ml/artifacts/baseline_distribution.json  (score distribution at training
    time, used by the weekly drift check to detect divergence later)
"""
import json
import os
import sys
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, roc_auc_score

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from generate_vendor_dataset import build_dataset, FEATURE_COLUMNS, LABEL_COLUMN, OUT_CSV, main as generate_main

ARTIFACT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "artifacts")
MODEL_PATH = os.path.join(ARTIFACT_DIR, "model.joblib")
VERSION_PATH = os.path.join(ARTIFACT_DIR, "model_version.txt")
BASELINE_PATH = os.path.join(ARTIFACT_DIR, "baseline_distribution.json")

# Vendors often have only some signals on file. The model learns to score
# with gaps (scikit-learn >= 1.4 forests handle NaN) from a copy of the
# training rows with this share of values blanked, so a missing value is
# left out rather than filled with a guess that reads as risk.
MISSING_RATE = 0.2
MODEL_PARAMS = dict(n_estimators=200, max_depth=6, random_state=42, class_weight="balanced")


def with_missing(X: pd.DataFrame, rate: float = MISSING_RATE, seed: int = 7) -> pd.DataFrame:
    """A copy of X with `rate` of the values blanked at random."""
    rng = np.random.default_rng(seed)
    out = X.astype(float).copy()
    out[rng.random(out.shape) < rate] = np.nan
    return out


def split(df: pd.DataFrame):
    X = df[FEATURE_COLUMNS]
    y = df[LABEL_COLUMN]
    return train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)


def fit(X_train: pd.DataFrame, y_train: pd.Series) -> RandomForestClassifier:
    model = RandomForestClassifier(**MODEL_PARAMS)
    model.fit(pd.concat([X_train.astype(float), with_missing(X_train)]), pd.concat([y_train, y_train]))
    return model


def _try_mlflow():
    try:
        import mlflow
        return mlflow
    except Exception:
        return None


def train():
    os.makedirs(ARTIFACT_DIR, exist_ok=True)

    if not os.path.exists(OUT_CSV):
        generate_main()
    df = pd.read_csv(OUT_CSV) if os.path.exists(OUT_CSV) else build_dataset()

    X = df[FEATURE_COLUMNS]
    X_train, X_test, y_train, y_test = split(df)
    model = fit(X_train, y_train)

    preds = model.predict(X_test)
    proba = model.predict_proba(X_test)[:, 1]
    accuracy = accuracy_score(y_test, preds)
    try:
        auc = roc_auc_score(y_test, proba)
    except ValueError:
        auc = float("nan")

    version = datetime.now(timezone.utc).strftime("v%Y%m%d%H%M%S")

    joblib.dump({"model": model, "features": FEATURE_COLUMNS}, MODEL_PATH)
    with open(VERSION_PATH, "w") as f:
        f.write(version)

    # Baseline score distribution over the full training set, for the
    # drift-monitoring PSI check to compare future scores against.
    all_scores = model.predict_proba(X)[:, 1]
    bins = np.linspace(0, 1, 11)
    hist, _ = np.histogram(all_scores, bins=bins)
    baseline = {
        "version": version,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "bin_edges": bins.tolist(),
        "counts": hist.tolist(),
        "n_samples": int(len(all_scores)),
    }
    with open(BASELINE_PATH, "w") as f:
        json.dump(baseline, f, indent=2)

    # Skipped during the image build (no MLflow server there); run
    # `python ml/train_risk_model.py` in the running container to log a run.
    mlflow = None if os.environ.get("SKIP_MLFLOW") else _try_mlflow()
    if mlflow is not None:
        try:
            os.environ["MLFLOW_HTTP_REQUEST_TIMEOUT"] = "2"
            mlflow.set_tracking_uri(os.environ.get("APP_MLFLOW_TRACKING_URI", "http://mlflow:5000"))
            mlflow.set_experiment("vendor_risk_classifier")
            with mlflow.start_run(run_name=version):
                mlflow.log_param("n_estimators", MODEL_PARAMS["n_estimators"])
                mlflow.log_param("max_depth", MODEL_PARAMS["max_depth"])
                mlflow.log_param("missing_rate", MISSING_RATE)
                mlflow.log_param("features", FEATURE_COLUMNS)
                mlflow.log_metric("accuracy", accuracy)
                if not np.isnan(auc):
                    mlflow.log_metric("roc_auc", auc)
                mlflow.log_artifact(MODEL_PATH)
                mlflow.log_artifact(BASELINE_PATH)
                mlflow.set_tag("model_version", version)
        except Exception as e:
            print(f"MLflow logging skipped (tracking server unreachable): {e}")

    print(f"Trained {version}: accuracy={accuracy:.3f} auc={auc:.3f}")
    return version


if __name__ == "__main__":
    train()
