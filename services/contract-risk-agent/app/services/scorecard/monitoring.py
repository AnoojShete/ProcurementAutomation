"""Weekly descriptive monitoring report (Prompt 9B section 12).
Replaces legacy PSI drift monitoring. No statistical inference for decisions.
Provides descriptive calibration metrics for the ruleset and alerts when collector availability drops.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from sqlalchemy import case, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import (
    RiskScore,
    RiskScoreRuleResult,
    Vendor,
    VendorSignalObservation,
    VendorSignalRawResponse,
)


async def generate_monitoring_report(db: AsyncSession) -> Dict[str, Any]:
    """Generates the weekly descriptive monitoring report for System Health."""
    now = datetime.now(timezone.utc)
    one_week_ago = now - timedelta(days=7)
    four_weeks_ago = now - timedelta(days=28)

    # 1. Vendor distribution per band (latest score per vendor)
    latest_score_subq = (
        select(RiskScore.vendor_id, func.max(RiskScore.scored_at).label("max_scored"))
        .group_by(RiskScore.vendor_id)
        .subquery()
    )

    vendor_bands_query = (
        select(RiskScore.final_band, func.count(RiskScore.id))
        .join(
            latest_score_subq,
            (RiskScore.vendor_id == latest_score_subq.c.vendor_id)
            & (RiskScore.scored_at == latest_score_subq.c.max_scored),
        )
        .group_by(RiskScore.final_band)
    )
    band_rows = (await db.execute(vendor_bands_query)).all()
    band_counts = {"Low": 0, "Medium": 0, "High": 0}
    for b, count in band_rows:
        if b in band_counts:
            band_counts[b] = count

    # 2. Rule firing frequency (in the last 4 weeks)
    rule_firing_query = (
        select(RiskScoreRuleResult.rule_id, RiskScoreRuleResult.signal_key, func.count(RiskScoreRuleResult.id))
        .join(RiskScore, RiskScoreRuleResult.score_id == RiskScore.id)
        .where(RiskScore.scored_at >= four_weeks_ago)
        .group_by(RiskScoreRuleResult.rule_id, RiskScoreRuleResult.signal_key)
        .order_by(func.count(RiskScoreRuleResult.id).desc())
        .limit(20)
    )
    rule_firing_rows = (await db.execute(rule_firing_query)).all()
    rule_frequencies = [
        {"rule_id": r[0], "signal_key": r[1], "count": r[2]}
        for r in rule_firing_rows
    ]

    # 3. Signals most often not assessed
    na_query = (
        select(RiskScoreRuleResult.signal_key, func.count(RiskScoreRuleResult.id))
        .join(RiskScore, RiskScoreRuleResult.score_id == RiskScore.id)
        .where(
            (RiskScore.scored_at >= four_weeks_ago)
            & (RiskScoreRuleResult.status == "not_assessed")
        )
        .group_by(RiskScoreRuleResult.signal_key)
        .order_by(func.count(RiskScoreRuleResult.id).desc())
    )
    na_rows = (await db.execute(na_query)).all()
    signals_not_assessed = [{"signal_key": r[0], "count": r[1]} for r in na_rows]

    # 4. Collector success rates (last 7 days vs 4 weeks)
    recent_coll_query = (
        select(
            VendorSignalObservation.signal_key,
            func.count(VendorSignalObservation.id).label("total"),
            func.sum(case((VendorSignalObservation.status.in_(["ok", "not_applicable"]), 1), else_=0)).label("successful"),
        )
        .where(VendorSignalObservation.fetched_at >= one_week_ago)
        .group_by(VendorSignalObservation.signal_key)
    )

    collector_health = []
    # Query raw responses for status 200/ok
    raw_health_query = (
        select(
            VendorSignalRawResponse.signal_key,
            func.count(VendorSignalRawResponse.id).label("total"),
            func.sum(case(((VendorSignalRawResponse.response_status < 400)
                           | (VendorSignalRawResponse.error.is_(None)), 1), else_=0)).label("ok_count"),
        )
        .where(VendorSignalRawResponse.fetched_at >= one_week_ago)
        .group_by(VendorSignalRawResponse.signal_key)
    )
    raw_health_rows = (await db.execute(raw_health_query)).all()
    alerts = []
    for sig, total, ok in raw_health_rows:
        rate = round((ok / total) * 100, 1) if total > 0 else 100.0
        collector_health.append({
            "signal_key": sig,
            "calls_7d": total,
            "success_rate_pct": rate,
        })
        if rate < 75.0 and total >= 5:
            alerts.append(f"Collector '{sig}' availability is {rate}% in the past 7 days (sharp drop alert).")

    # 5. Incident Calibration: vendors that had an incident within 12 months
    calibration_query = text("""
        SELECT r.final_band, count(r.id)
        FROM risk_scores r
        WHERE EXISTS (
            SELECT 1 FROM vendor_signal_observations o
            WHERE o.vendor_id = r.vendor_id
              AND o.signal_key = 'incidents'
              AND (o.fields->>'inc.count_24m')::int > 0
              AND o.fetched_at BETWEEN r.scored_at AND r.scored_at + interval '12 months'
        )
        GROUP BY r.final_band
    """)
    calib_rows = (await db.execute(calibration_query)).all()
    incident_band_distribution = {r[0]: r[1] for r in calib_rows if r[0]}

    return {
        "generated_at": now.isoformat(),
        "vendor_band_distribution": band_counts,
        "rule_frequencies_4w": rule_frequencies,
        "signals_often_not_assessed": signals_not_assessed,
        "collector_health": collector_health,
        "incident_calibration": incident_band_distribution,
        "alerts": alerts,
    }
