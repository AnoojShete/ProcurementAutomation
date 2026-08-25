"""Model drift monitoring.

This is a monitoring signal, not an automated retraining pipeline: it
computes a basic Population Stability Index (PSI) between the score
distribution at training time (ml/artifacts/baseline_distribution.json)
and the distribution of the last N scores actually produced in
production, and logs a `model_drift_detected` flag to MLflow for a human
to review. It does not retrain or change model behavior on its own.
"""
import json
import os
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import load_drift_config
from app.models import RiskScore

ARTIFACT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "ml", "artifacts"
)
BASELINE_PATH = os.path.join(ARTIFACT_DIR, "baseline_distribution.json")


def _population_stability_index(baseline_counts, current_counts) -> float:
    baseline = np.array(baseline_counts, dtype=float)
    current = np.array(current_counts, dtype=float)
    baseline = baseline / max(baseline.sum(), 1)
    current = current / max(current.sum(), 1)
    # avoid log(0) / div-by-0 on empty bins
    baseline = np.clip(baseline, 1e-4, None)
    current = np.clip(current, 1e-4, None)
    return float(np.sum((current - baseline) * np.log(current / baseline)))


async def check_drift(db: AsyncSession) -> dict:
    cfg = load_drift_config()
    min_n = cfg.get("min_outcomes_for_check", 5)
    threshold = cfg.get("psi_threshold", 0.2)

    if not os.path.exists(BASELINE_PATH):
        return {"checked": False, "reason": "no baseline distribution yet — train the model first"}

    with open(BASELINE_PATH) as f:
        baseline = json.load(f)

    n_recent = max(baseline.get("n_samples", 100), 50)
    result = await db.execute(select(RiskScore.score).order_by(RiskScore.scored_at.desc()).limit(n_recent))
    recent_scores = [float(s) for (s,) in result.all()]

    if len(recent_scores) < min_n:
        return {"checked": False, "reason": f"only {len(recent_scores)} recent scores, need >= {min_n}"}

    bin_edges = baseline["bin_edges"]
    current_counts, _ = np.histogram(recent_scores, bins=bin_edges)
    psi = _population_stability_index(baseline["counts"], current_counts.tolist())
    drift_detected = psi > threshold

    _log_to_mlflow(psi, drift_detected, baseline.get("version"))

    return {
        "checked": True,
        "psi": round(psi, 4),
        "threshold": threshold,
        "model_drift_detected": drift_detected,
        "n_recent_scores": len(recent_scores),
        "baseline_model_version": baseline.get("version"),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def _log_to_mlflow(psi: float, drift_detected: bool, baseline_version: str | None):
    try:
        import mlflow

        mlflow.set_experiment("vendor_risk_classifier")
        with mlflow.start_run(run_name=f"drift-check-{datetime.now(timezone.utc).isoformat()}"):
            mlflow.log_metric("psi", psi)
            mlflow.set_tag("model_drift_detected", str(drift_detected))
            mlflow.set_tag("baseline_model_version", baseline_version or "unknown")
    except Exception:
        pass  # MLflow unreachable — drift result is still returned to the caller
