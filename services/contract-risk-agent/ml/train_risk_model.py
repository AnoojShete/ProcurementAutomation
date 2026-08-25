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
    y = df[LABEL_COLUMN]
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)

    model = RandomForestClassifier(n_estimators=200, max_depth=6, random_state=42, class_weight="balanced")
    model.fit(X_train, y_train)

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

    mlflow = _try_mlflow()
    if mlflow is not None:
        try:
            mlflow.set_tracking_uri(os.environ.get("APP_MLFLOW_TRACKING_URI", "http://mlflow:5000"))
            mlflow.set_experiment("vendor_risk_classifier")
            with mlflow.start_run(run_name=version):
                mlflow.log_param("n_estimators", 200)
                mlflow.log_param("max_depth", 6)
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
