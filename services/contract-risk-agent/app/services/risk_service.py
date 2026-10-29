"""Deterministic rule-based vendor risk scorecard service (Prompt 9B).
Replaces ML model scoring with 100% deterministic integer points (0-100).
"""
import copy
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.metrics import risk_assessment_total
from app.models import (
    RiskRuleset,
    RiskScore,
    RiskScoreRuleResult,
    Vendor,
    VendorSignalObservation,
)
from app.services.collectors.collector_manager import collect_all_signals
from app.services.scorecard.default_ruleset import (
    canonical_json_hash,
    get_default_ruleset,
)
from app.services.scorecard.engine import evaluate_risk, calculate_effective_tier
from shared.eventing import staged
from shared.rules_engine import get_rule

logger = logging.getLogger(__name__)


async def get_active_ruleset(db: AsyncSession) -> RiskRuleset:
    """Retrieves the active ruleset version, or seeds default ruleset v1 if none exists."""
    result = await db.execute(
        select(RiskRuleset).where(RiskRuleset.status == "active").order_by(RiskRuleset.version.desc()).limit(1)
    )
    ruleset = result.scalars().first()
    if ruleset is None:
        default_def = get_default_ruleset()
        d_hash = canonical_json_hash(default_def)
        ruleset = RiskRuleset(
            id=str(uuid.uuid4()),
            version=1,
            status="active",
            definition=default_def,
            definition_hash=d_hash,
            created_by="system",
            created_at=datetime.now(timezone.utc),
            activated_by="system",
            activated_at=datetime.now(timezone.utc),
            change_justification="Initial seed of default ruleset v1 (Prompt 9B)",
        )
        db.add(ruleset)
        await db.flush()
        logger.info("Seeded default ruleset v1 as active")
    return ruleset


async def load_fresh_observations(
    db: AsyncSession, vendor_id: str, ruleset: Dict[str, Any], now: datetime
) -> Dict[str, Any]:
    """Loads latest observations for each signal from DB that are still within their TTL."""
    signals_def = ruleset.get("signals", [])
    observations = {}
    for sig in signals_def:
        sig_key = sig["key"]
        ttl_days = sig.get("ttl_days", 30)
        # Query latest observation
        res = await db.execute(
            select(VendorSignalObservation)
            .where(
                VendorSignalObservation.vendor_id == vendor_id,
                VendorSignalObservation.signal_key == sig_key,
            )
            .order_by(VendorSignalObservation.fetched_at.desc())
            .limit(1)
        )
        obs = res.scalars().first()
        if obs and obs.fetched_at:
            f_dt = obs.fetched_at if obs.fetched_at.tzinfo else obs.fetched_at.replace(tzinfo=timezone.utc)
            if (now - f_dt).total_seconds() <= ttl_days * 86400:
                observations[sig_key] = obs
    return observations


async def send_high_risk_alert(kafka_producer, vendor, vendor_id: str, headline, total_points, final_band,
                               top_factors: list) -> bool:
    """E-mails rule risk.alert_recipients when a vendor turns High or a new
    hard override fires. Returns whether an alert was sent."""
    recipients = get_rule("risk.alert_recipients", fallback="procurement-risk-team@company.com")
    if not recipients:
        logger.warning(f"High risk transition for vendor {vendor_id} but risk.alert_recipients is empty; omitting email.")
        return False
    await kafka_producer.publish_notification(
        recipient=recipients,
        channel="email",
        template_name="vendor_high_risk_alert",
        template_context={
            "vendor_id": vendor_id,
            "vendor_name": vendor.name,
            "headline": headline,
            "total_points": total_points,
            "final_band": final_band,
            "top_factors": top_factors[:3],
            "link": f"/app/vendors/{vendor_id}/risk",
        },
        priority="urgent",
        related_entity_id=vendor_id,
    )
    return True


async def score_vendor(
    db: AsyncSession,
    kafka_producer,
    vendor_id: str,
    trigger_type: str = "manual",
    trigger_ref: Optional[str] = None,
    force_fresh_collect: bool = True,
) -> RiskScore:
    """Evaluates vendor risk using the active deterministic ruleset and stores score & rule results."""
    now = datetime.now(timezone.utc)

    # 1. Vendor existence check
    vendor = await db.get(Vendor, vendor_id)
    if vendor is None:
        raise ValueError(f"vendor {vendor_id} not found")

    # 2. Get active ruleset
    ruleset_row = await get_active_ruleset(db)
    ruleset_def = ruleset_row.definition

    # 3. Vendor context & tier
    v_row = (await db.execute(
        text("SELECT vendor_tier, inherent_tier, country FROM vendors WHERE id = :id"),
        {"id": vendor_id},
    )).first()
    spend_tier = (v_row.vendor_tier if v_row else "standard") or "standard"
    inh_tier = v_row.inherent_tier if v_row else getattr(vendor, "inherent_tier", None)
    effective_tier, _ = calculate_effective_tier(spend_tier, inh_tier)

    vendor_context = {
        "name": vendor.name,
        "spend_tier": spend_tier,
        "inherent_tier": inh_tier,
        # Without the country every vendor came out provisional ("vendor
        # country missing"), even one onboarded with it (merge review G3).
        "country": getattr(vendor, "country", None) or (v_row.country if v_row else None),
        "ruleset_version": getattr(ruleset_row, "version", None),
    }

    # 4. Gather observations (run collectors or load fresh)
    if force_fresh_collect:
        observations = await collect_all_signals(db, vendor, now=now, effective_tier=effective_tier,
                                                 lexicon=ruleset_def.get("lookups", {}).get("adverse_media_lexicon"))
    else:
        observations = await load_fresh_observations(db, vendor_id, ruleset_def, now)
        if len(observations) < len(ruleset_def.get("signals", [])):
            fresh_obs = await collect_all_signals(db, vendor, now=now, effective_tier=effective_tier,
                                                 lexicon=ruleset_def.get("lookups", {}).get("adverse_media_lexicon"))
            for k, v in fresh_obs.items():
                if k not in observations:
                    observations[k] = v

    # 5. Fetch previous score for delta and alert tracking
    prev_score = await latest_risk_score(db, vendor_id)
    prev_dict = None
    if prev_score:
        prev_res = await db.execute(
            select(RiskScoreRuleResult).where(RiskScoreRuleResult.score_id == prev_score.id)
        )
        prev_rule_rows = prev_res.scalars().all()
        prev_dict = {
            "total_points": prev_score.total_points,
            "final_band": prev_score.final_band or prev_score.band,
            "rule_results": [
                {"signal_key": r.signal_key, "rule_id": r.rule_id, "points": r.points}
                for r in prev_rule_rows
            ],
            "override_rule_ids": prev_score.override_rule_ids or [],
        }

    # 6. Run pure evaluation function
    eval_result = evaluate_risk(
        ruleset=ruleset_def,
        observations=observations,
        assessed_at=now,
        vendor_context=vendor_context,
        previous_score=prev_dict,
        trigger_type=trigger_type,
        trigger_ref=trigger_ref,
    )

    total_points = eval_result["total_points"]
    final_band = eval_result["final_band"]
    points_band = eval_result["points_band"]
    override_ids = eval_result["override_rule_ids"]

    # Top factors for backward compatibility in details column
    top_factors = []
    for r in eval_result["rule_results"]:
        if r["points"] > 0 or r["override_band"]:
            top_factors.append({
                "feature": r["signal_key"],
                "rule_id": r["rule_id"],
                "contribution": round(r["points"] / 100.0, 4),
                "override": bool(r["override_band"]),
                "reason": r["reason_text"],
            })
    top_factors.sort(key=lambda x: x["contribution"], reverse=True)

    score_id = str(uuid.uuid4())
    score_row = RiskScore(
        id=score_id,
        vendor_id=vendor_id,
        score=eval_result.get("risk_score"),
        band=final_band,
        details=top_factors[:5],
        model_version=f"ruleset_v{ruleset_row.version}",
        scored_at=now,
        signals_used=sum(1 for r in eval_result["rule_results"] if r["status"] == "assessed"),
        signals_total=len(eval_result["rule_results"]),
        overrides=[{"rule_id": oid, "status": "triggered"} for oid in override_ids],
        ruleset_id=ruleset_row.id,
        ruleset_version=ruleset_row.version,
        total_points=total_points,
        points_band=points_band,
        final_band=final_band,
        override_rule_ids=override_ids,
        unassessed_potential_points=eval_result["unassessed_potential_points"],
        worst_case_points=eval_result["worst_case_points"],
        worst_case_band=eval_result["worst_case_band"],
        is_provisional=eval_result["is_provisional"],
        provisional_reasons=eval_result["provisional_reasons"],
        effective_tier=eval_result["effective_tier"],
        headline=eval_result["headline"],
        explanation=eval_result["explanation"],
        observation_ids=eval_result["observation_ids"],
        snapshot=eval_result["snapshot"],
        snapshot_sha256=eval_result["snapshot_sha256"],
        assessed_at=now,
        trigger_type=trigger_type,
        trigger_ref=trigger_ref,
        previous_score_id=prev_score.id if prev_score else None,
        rating_status=eval_result.get("rating_status", "not_rated"),
        applicable_max_points=eval_result.get("applicable_max_points", 100),
        due_diligence_potential_points=eval_result.get("due_diligence_potential_points", 0),
        history_potential_points=eval_result.get("history_potential_points", 0),
        points_is_lower_bound=eval_result.get("points_is_lower_bound", False),
        blocked_by=eval_result.get("blocked_by", []),
        remediation_path=eval_result.get("remediation_path", []),
    )
    db.add(score_row)
    await db.flush()

    # 7. Persist rule results
    for r in eval_result["rule_results"]:
        rr_row = RiskScoreRuleResult(
            id=str(uuid.uuid4()),
            score_id=score_id,
            order_index=r["order_index"],
            signal_key=r["signal_key"],
            group_key=r["group_key"],
            rule_id=r["rule_id"],
            rule_version_hash=ruleset_row.definition_hash[:16],
            status=r["status"],
            points=r["points"],
            potential_points=r["potential_points"],
            override_band=r["override_band"],
            observed_fields=r["observed_fields"],
            facts=r["facts"],
            reason_text=r["reason_text"],
            rationale=r["rationale"],
            observation_id=r["observation_id"],
            raw_response_id=r["raw_response_id"],
            remediation=r["remediation"],
            remediable=r["remediable"],
            ages_out_on=datetime.strptime(r["ages_out_on"], "%Y-%m-%d").date() if r.get("ages_out_on") else None,
        )
        db.add(rr_row)

    risk_assessment_total.labels(risk_band=final_band).inc()

    # 8. Alerting & event publishing, through the outbox so the events commit
    # together with the score (merge review G6).
    previous_band = prev_score.band if prev_score else None
    band_changed = (prev_score is not None and prev_score.band != final_band)
    prev_overrides = set(prev_dict.get("override_rule_ids", [])) if prev_dict else set()
    new_override_fired = any(oid not in prev_overrides for oid in override_ids)

    outbox = staged(kafka_producer, db)
    if outbox is not None:
        await outbox.publish_risk_score_updated(
            vendor_id=vendor_id,
            risk_band=final_band,
            risk_score=eval_result["score_float"],
            top_factors=top_factors,
            model_version=f"ruleset_v{ruleset_row.version}",
            scored_at=now,
            total_points=total_points,
            points_band=points_band,
            final_band=final_band,
            override_rule_ids=override_ids,
            unassessed_potential_points=eval_result["unassessed_potential_points"],
            worst_case_band=eval_result["worst_case_band"],
            ruleset_version=ruleset_row.version,
            is_provisional=eval_result["is_provisional"],
            effective_tier=eval_result["effective_tier"],
            previous_band=previous_band,
            band_changed=band_changed,
            trigger_type=trigger_type,
            explanation_url=f"/app/vendors/{vendor_id}/risk",
        )

        # Prompt 9B Section 11.2 Alert Policy:
        # Send High alert only when band_changed is true and new band is High, or an override rule newly fired.
        should_alert = (band_changed and final_band == "High") or new_override_fired
        if should_alert:
            await send_high_risk_alert(outbox, vendor, vendor_id, eval_result["headline"], total_points,
                                       final_band, top_factors)

    await db.commit()
    await db.refresh(score_row)
    return score_row


_DELIVERED_SINCE_SCORED = text("""
    SELECT DISTINCT pr.vendor_id::text
    FROM purchase_requests pr
    JOIN audit_log a ON a.entity_id = pr.id AND a.action IN ('contract_fulfilment_applied', 'goods_received')
    WHERE pr.vendor_id IS NOT NULL
      AND a.created_at > COALESCE((SELECT MAX(scored_at) FROM risk_scores r WHERE r.vendor_id = pr.vendor_id),
                                  'epoch'::timestamptz)
""")


async def rescore_after_deliveries(session_factory, kafka_producer) -> int:
    """Re-scores vendors with an order received since their last score."""
    async with session_factory() as db:
        vendor_ids = [r[0] for r in (await db.execute(_DELIVERED_SINCE_SCORED)).all()]
    for vendor_id in vendor_ids:
        async with session_factory() as db:
            await score_vendor(db, kafka_producer, vendor_id, trigger_type="delivery")
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


async def latest_risk_score(db: AsyncSession, vendor_id: str) -> Optional[RiskScore]:
    result = await db.execute(
        select(RiskScore).where(RiskScore.vendor_id == vendor_id).order_by(RiskScore.scored_at.desc()).limit(1)
    )
    return result.scalars().first()
