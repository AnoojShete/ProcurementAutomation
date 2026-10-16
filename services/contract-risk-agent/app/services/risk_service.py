import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from functools import lru_cache

import joblib
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import load_risk_config
from app.models import RiskScore, VendorRiskFeatures
from app.metrics import risk_assessment_total

logger = logging.getLogger(__name__)

ML_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "ml")
ARTIFACT_DIR = os.path.join(ML_DIR, "artifacts")
MODEL_PATH = os.path.join(ARTIFACT_DIR, "model.joblib")
VERSION_PATH = os.path.join(ARTIFACT_DIR, "model_version.txt")

# Hard overrides: a vendor that fails one of these is High whatever the
# model says (checked before the model, reported as the first factor).
# "not_checked" when the signal isn't on file — sanctions screening is
# FR-14, and IFSC results aren't stored yet.
GSTIN_FAILED = ("cancelled", "suspended")
GSTIN_NOT_CHECKED = (None, "", "unverified", "offline", "simulated")


class ModelNotTrainedError(Exception):
    pass


@lru_cache
def _load_model():
    if not os.path.exists(MODEL_PATH):
        sys.path.insert(0, ML_DIR)
        from train_risk_model import train  # local import: only needed the first time

        train()
    bundle = joblib.load(MODEL_PATH)
    with open(VERSION_PATH) as f:
        version = f.read().strip()
    return bundle["model"], bundle["features"], version


def _band_for_score(score: float) -> str:
    cfg = load_risk_config().get("bands", {"low_max": 0.33, "medium_max": 0.66})
    if score <= cfg.get("low_max", 0.33):
        return "Low"
    if score <= cfg.get("medium_max", 0.66):
        return "Medium"
    return "High"


async def _load_features(db: AsyncSession, vendor_id: str) -> dict:
    """The model's inputs for a vendor; None where nothing is on file. A
    missing value is left out (the model was trained with gaps), never
    filled with a default that would read as risk."""
    row = await db.get(VendorRiskFeatures, vendor_id)
    if row is None:
        return {name: None for name in FEATURE_NAMES}

    def num(v, cast=float):
        return cast(v) if v is not None else None

    return {
        "vendor_tenure_months": num(row.vendor_tenure_months, int),
        "on_time_delivery_rate": num(row.on_time_delivery_rate),
        "financial_stability_score": num(row.financial_stability_score),
        "breach_disclosure_count": num(row.breach_disclosure_count, int),
        # Booleans default to false in the table, so "not set" can't be told
        # apart from "no": they count as known.
        "security_cert_flag": int(bool(row.security_cert_flag)),
        "geo_risk_flag": int(bool(row.geo_risk_flag)),
    }


FEATURE_NAMES = [
    "vendor_tenure_months", "on_time_delivery_rate", "financial_stability_score",
    "breach_disclosure_count", "security_cert_flag", "geo_risk_flag",
]


def hard_override_checks(gstin_status: str | None, sanctions_match: bool | None = None,
                         ifsc_status: str | None = None) -> list[dict]:
    """Each check: triggered (vendor is High), clear, or not_checked."""
    status = (gstin_status or "").lower() or None
    checks = [{
        "check": "gstin",
        "status": "triggered" if status in GSTIN_FAILED else "not_checked" if status in GSTIN_NOT_CHECKED else "clear",
        "reason": f"GSTIN is {status}" if status in GSTIN_FAILED else None,
    }, {
        "check": "sanctions",
        "status": "not_checked" if sanctions_match is None else "triggered" if sanctions_match else "clear",
        "reason": "matched a sanctions list" if sanctions_match else None,
    }, {
        "check": "ifsc",
        "status": "not_checked" if ifsc_status is None else "triggered" if ifsc_status == "invalid" else "clear",
        "reason": "bank IFSC failed verification" if ifsc_status == "invalid" else None,
    }]
    return checks


def assess(model, feature_order: list[str], features: dict, override_checks: list[dict]) -> dict:
    """Score, band and factors for one vendor. Overrides beat the model: the
    model's score is kept (for drift monitoring) but the band is High and
    the override is the first factor."""
    import numpy as np
    X = [[np.nan if features.get(name) is None else features[name] for name in feature_order]]
    score = float(model.predict_proba(X)[0][1])
    band = _band_for_score(score)
    factors = _top_factors(model, features, feature_order)
    triggered = [c for c in override_checks if c["status"] == "triggered"]
    if triggered:
        band = "High"
        factors = [{"feature": f"override:{c['check']}", "contribution": 1.0, "override": True, "reason": c["reason"]}
                   for c in triggered] + factors
    used = sum(1 for name in feature_order if features.get(name) is not None)
    return {"score": score, "band": band, "top_factors": factors,
            "signals_used": used, "signals_total": len(feature_order)}


def _top_factors(model, features: dict, feature_order: list[str], top_n: int = 3) -> list[dict]:
    """feature_importances_ gives global importance; scaled by how far this
    vendor's value sits from a neutral midpoint so the factors reported are
    specific to this vendor, not just a static ranking repeated for every
    vendor."""
    importances = model.feature_importances_
    contributions = []
    for name, importance in zip(feature_order, importances):
        value = features.get(name)
        if value is None:
            continue  # not on file: not a factor either way
        if name in ("security_cert_flag",):
            deviation = -(value - 0.5) * 2  # having the cert LOWERS risk
        elif name in ("geo_risk_flag", "breach_disclosure_count"):
            deviation = value if isinstance(value, (int, float)) and value <= 1 else min(value / 3.0, 1.0)
        elif name == "vendor_tenure_months":
            deviation = -(min(value, 60) / 60.0 - 0.5) * 2
        else:
            deviation = (0.5 - value) * 2  # lower rate/score => higher risk contribution
        contributions.append({"feature": name, "contribution": round(float(importance * abs(deviation)), 4)})
    contributions.sort(key=lambda c: c["contribution"], reverse=True)
    return contributions[:top_n]


async def score_vendor(db: AsyncSession, kafka_producer, vendor_id: str) -> RiskScore:
    from app.services.risk_signals import refresh_platform_signals
    model, feature_order, version = _load_model()
    # BR-7: tenure and on-time delivery from platform history, every time.
    await refresh_platform_signals(db, vendor_id)
    await db.flush()
    features = await _load_features(db, vendor_id)
    gstin_status = (await db.execute(
        text("SELECT gstin_verification_status FROM vendors WHERE id = :id"), {"id": vendor_id}
    )).scalar_one_or_none()
    checks = hard_override_checks(gstin_status)
    result = assess(model, feature_order, features, checks)
    risk_score, band, top_factors = result["score"], result["band"], result["top_factors"]
    scored_at = datetime.now(timezone.utc)

    row = RiskScore(
        id=str(uuid.uuid4()),
        vendor_id=vendor_id,
        score=risk_score,
        band=band,
        details=top_factors,
        model_version=version,
        scored_at=scored_at,
        signals_used=result["signals_used"],
        signals_total=result["signals_total"],
        overrides=checks,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    risk_assessment_total.labels(risk_band=band).inc()

    if kafka_producer is not None:
        await kafka_producer.publish_risk_score_updated(
            vendor_id=vendor_id,
            risk_band=band,
            risk_score=risk_score,
            top_factors=top_factors,
            model_version=version,
            scored_at=scored_at,
        )
        if band == "High":
            await kafka_producer.publish_notification(
                recipient="procurement-risk-team@company.com",
                channel="email",
                template_name="vendor_high_risk_alert",
                template_context={"vendor_id": vendor_id, "risk_score": risk_score, "top_factors": top_factors},
                priority="urgent",
                related_entity_id=vendor_id,
            )
    return row


_DELIVERED_SINCE_SCORED = text("""
    SELECT DISTINCT pr.vendor_id::text
    FROM purchase_requests pr
    JOIN audit_log a ON a.entity_id = pr.id AND a.action = 'contract_fulfilment_applied'
    WHERE pr.vendor_id IS NOT NULL
      AND a.created_at > COALESCE((SELECT MAX(scored_at) FROM risk_scores r WHERE r.vendor_id = pr.vendor_id),
                                  'epoch'::timestamptz)
""")


async def rescore_after_deliveries(session_factory, kafka_producer) -> int:
    """Re-scores vendors with an order received since their last score, so
    on-time delivery reaches the score without waiting for a recompute."""
    async with session_factory() as db:
        vendor_ids = [r[0] for r in (await db.execute(_DELIVERED_SINCE_SCORED)).all()]
    for vendor_id in vendor_ids:
        async with session_factory() as db:
            await score_vendor(db, kafka_producer, vendor_id)
    if vendor_ids:
        logger.info(f"Re-scored {len(vendor_ids)} vendor(s) after deliveries")
    return len(vendor_ids)


async def run_delivery_rescore(session_factory, kafka_producer, interval_seconds: int = 300):
    import asyncio
    while True:
        try:
            await rescore_after_deliveries(session_factory, kafka_producer)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"Delivery re-score sweep failed: {e}", exc_info=True)
        await asyncio.sleep(interval_seconds)


async def latest_risk_score(db: AsyncSession, vendor_id: str) -> RiskScore | None:
    result = await db.execute(
        select(RiskScore).where(RiskScore.vendor_id == vendor_id).order_by(RiskScore.scored_at.desc()).limit(1)
    )
    return result.scalars().first()
