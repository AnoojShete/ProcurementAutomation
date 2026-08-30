import os
import sys
import uuid
from datetime import datetime, timezone
from functools import lru_cache

import joblib
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import load_risk_config
from app.models import RiskScore, VendorRiskFeatures
from app.metrics import risk_assessment_total

ML_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "ml")
ARTIFACT_DIR = os.path.join(ML_DIR, "artifacts")
MODEL_PATH = os.path.join(ARTIFACT_DIR, "model.joblib")
VERSION_PATH = os.path.join(ARTIFACT_DIR, "model_version.txt")

DEFAULT_FEATURES = {
    "vendor_tenure_months": 0,
    "on_time_delivery_rate": 0.5,
    "financial_stability_score": 0.5,
    "breach_disclosure_count": 0,
    "security_cert_flag": 0,
    "geo_risk_flag": 0,
}


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
    row = await db.get(VendorRiskFeatures, vendor_id)
    if row is None:
        return dict(DEFAULT_FEATURES)
    return {
        "vendor_tenure_months": row.vendor_tenure_months or 0,
        "on_time_delivery_rate": float(row.on_time_delivery_rate) if row.on_time_delivery_rate is not None else 0.5,
        "financial_stability_score": float(row.financial_stability_score) if row.financial_stability_score is not None else 0.5,
        "breach_disclosure_count": row.breach_disclosure_count or 0,
        "security_cert_flag": int(bool(row.security_cert_flag)),
        "geo_risk_flag": int(bool(row.geo_risk_flag)),
    }


def _top_factors(model, features: dict, feature_order: list[str], top_n: int = 3) -> list[dict]:
    """feature_importances_ gives global importance; scaled by how far this
    vendor's value sits from a neutral midpoint so the factors reported are
    specific to this vendor, not just a static ranking repeated for every
    vendor."""
    importances = model.feature_importances_
    contributions = []
    for name, importance in zip(feature_order, importances):
        value = features[name]
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
    model, feature_order, version = _load_model()
    features = await _load_features(db, vendor_id)
    X = [[features[name] for name in feature_order]]
    risk_score = float(model.predict_proba(X)[0][1])
    band = _band_for_score(risk_score)
    top_factors = _top_factors(model, features, feature_order)
    scored_at = datetime.now(timezone.utc)

    row = RiskScore(
        id=str(uuid.uuid4()),
        vendor_id=vendor_id,
        score=risk_score,
        band=band,
        details=top_factors,
        model_version=version,
        scored_at=scored_at,
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


async def latest_risk_score(db: AsyncSession, vendor_id: str) -> RiskScore | None:
    result = await db.execute(
        select(RiskScore).where(RiskScore.vendor_id == vendor_id).order_by(RiskScore.scored_at.desc()).limit(1)
    )
    return result.scalars().first()
