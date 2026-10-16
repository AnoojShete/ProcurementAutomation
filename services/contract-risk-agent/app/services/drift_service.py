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
MIN_SIGNALS_FOR_DRIFT = 3  # of the model's 6 inputs


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
    from shared.rules_engine import get_rule
    threshold = float(get_rule("risk.psi_significant_threshold", fallback=cfg.get("psi_threshold", 0.2)))
    moderate_threshold = float(get_rule("risk.psi_moderate_threshold", fallback=0.1))

    if not os.path.exists(BASELINE_PATH):
        return {"checked": False, "reason": "no baseline distribution yet — train the model first"}

    with open(BASELINE_PATH) as f:
        baseline = json.load(f)

    n_recent = max(baseline.get("n_samples", 100), 50)
    # BR-7: each vendor's latest score, and only where the model had real
    # inputs. A vendor with (almost) nothing on file gets the model's
    # "unknown" score, and re-scoring one vendor ten times isn't ten
    # vendors — counting either measured missing data, not drift.
    latest = (select(RiskScore.vendor_id, RiskScore.score, RiskScore.signals_used, RiskScore.scored_at)
              .distinct(RiskScore.vendor_id)
              .order_by(RiskScore.vendor_id, RiskScore.scored_at.desc())).subquery()
    rows = (await db.execute(
        select(latest.c.score, latest.c.signals_used).order_by(latest.c.scored_at.desc()))).all()
    recent_scores = [float(r.score) for r in rows if (r.signals_used or 0) >= MIN_SIGNALS_FOR_DRIFT][:n_recent]
    excluded = sum(1 for r in rows if (r.signals_used or 0) < MIN_SIGNALS_FOR_DRIFT)

    if len(recent_scores) < min_n:
        return {"checked": False, "excluded_low_signal_scores": excluded,
                "reason": f"only {len(recent_scores)} vendors scored on ≥ {MIN_SIGNALS_FOR_DRIFT} signals, need >= {min_n}; "
                          f"{excluded} vendors have too little on file to compare"}

    bin_edges = baseline["bin_edges"]
    current_counts, _ = np.histogram(recent_scores, bins=bin_edges)
    psi = _population_stability_index(baseline["counts"], current_counts.tolist())
    drift_detected = psi > threshold
    moderate_drift = psi > moderate_threshold

    _log_to_mlflow(psi, drift_detected, baseline.get("version"))

    return {
        "checked": True,
        "psi": round(psi, 4),
        "threshold": threshold,
        "moderate_threshold": moderate_threshold,
        "model_drift_detected": drift_detected,
        "moderate_drift_detected": moderate_drift,
        "n_recent_scores": len(recent_scores),
        "min_signals": MIN_SIGNALS_FOR_DRIFT,
        "excluded_low_signal_scores": excluded,
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
