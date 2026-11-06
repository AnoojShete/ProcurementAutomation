"""Vendor Risk API endpoints (Prompt 9B section 11.1).
Exposes deterministic risk scores, explanation payloads, remediation plans,
replay verification, audit bundles, disputes, and ruleset governance.
"""
import copy
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    VendorInherentTierHistory,
    AuditLog,
    RiskRuleset,
    RiskScore,
    RiskScoreRuleResult,
    Vendor,
    VendorAssessmentDispute,
    VendorDecision,
    VendorEvidence,
    VendorSignalObservation,
    VendorSignalRawResponse,
    BreachVendorReview,
    VendorWaiver,
)
from app.schemas import DataResponse, LogOutcomeRequest, OffboardVendorRequest
from app.services import clearance, offboard_service, risk_service
from app.services.scorecard.engine import evaluate_risk
from app.services.scorecard.monitoring import generate_monitoring_report
from app.services.scorecard.remediation import build_remediation_plan, simulate_what_if
from app.services.scorecard.traceability import compile_audit_bundle, replay_assessment, snapshot_observations
from shared.auth import CurrentUser, get_current_user, require_role

logger = logging.getLogger(__name__)
router = APIRouter()


def _serialize_risk_summary(row: RiskScore, vendor_status: str = "active") -> dict:
    """Serializes the summary response for GET /vendors/{id}/risk."""
    return {
        "vendor_id": row.vendor_id,
        "vendor_status": vendor_status,
        "rating_status": row.rating_status or "assessed",
        "final_band": row.final_band or row.band or "Unrated",
        "risk_band": row.final_band or row.band or "Unrated",
        "total_points": row.total_points if row.total_points is not None else int(round((row.score or 0) * 100)),
        "risk_score": float(row.score) if row.score is not None else None,
        "points_band": row.points_band or row.band or "Low",
        "points_is_lower_bound": row.points_is_lower_bound or False,
        "applicable_max_points": row.applicable_max_points or 100,
        "due_diligence_potential_points": row.due_diligence_potential_points or 0,
        "history_potential_points": row.history_potential_points or 0,
        "blocked_by": row.blocked_by or [],
        "remediation_path": row.remediation_path or [],
        "range": {
            "worst_case_points": row.worst_case_points,
            "worst_case_band": row.worst_case_band,
            "unassessed_potential": row.unassessed_potential_points,
            "history_potential_points": row.history_potential_points or 0,
            "due_diligence_potential_points": row.due_diligence_potential_points or 0,
        },
        "provisional": {
            "is_provisional": row.is_provisional,
            "reasons": row.provisional_reasons or [],
        },
        "headline": row.headline,
        # Details missing from the vendor record that the score is waiting on
        "data_needed": (row.explanation or {}).get("data_needed", []),
        "effective_tier": row.effective_tier or "standard",
        "top_contributors": row.details or [],
        "top_factors": row.details or [],
        "ruleset_version": row.ruleset_version or 1,
        "model_version": getattr(row, "model_version", None) or (f"ruleset_v{row.ruleset_version}" if getattr(row, "ruleset_version", None) else "ruleset_v2"),
        "scored_at": row.scored_at.isoformat() if row.scored_at else None,
        "explanation_url": f"/app/vendors/{row.vendor_id}/risk",
        "score_id": str(row.id),
        "trigger_type": row.trigger_type or "manual",
        "signals_used": row.signals_used,
        "signals_total": row.signals_total,
        "overrides": row.overrides or [],
    }


@router.get("/", response_model=DataResponse)
async def list_vendors(limit: int = Query(100, ge=1, le=1000), db: AsyncSession = Depends(get_db)):
    """All vendors with their latest deterministic risk score."""
    result = await db.execute(select(Vendor).order_by(Vendor.created_at.desc().nulls_last()).limit(limit))
    vendors = list(result.scalars().all())
    rows = []
    for v in vendors:
        latest = await risk_service.latest_risk_score(db, v.id)
        rows.append({
            "id": v.id,
            "name": v.name,
            "status": v.status,
            "inherent_tier": getattr(v, "inherent_tier", None),
            "swift_bic": getattr(v, "swift_bic", None),
            "bank_name": getattr(v, "bank_name", None),
            "website": getattr(v, "website", None),
            "portal_access_revoked": v.portal_access_revoked,
            "risk_band": (latest.final_band or latest.band) if latest else None,
            "risk_score": float(latest.score) if latest and latest.score is not None else None,
            "total_points": latest.total_points if latest else None,
            "final_band": (latest.final_band or latest.band) if latest else None,
            "rating_status": latest.rating_status if latest else None,
            "created_at": v.created_at.isoformat() if v.created_at else None,
        })
    return DataResponse(data=rows, meta={"count": len(rows)})


@router.get("/risk-parameters", response_model=DataResponse,
            dependencies=[Depends(require_role("approver", "finance", "admin"))])
async def risk_parameters(limit: int = Query(200, ge=1, le=1000), db: AsyncSession = Depends(get_db)):
    """Every vendor's latest score broken down by the parameters (signals)
    the ruleset considered: weight, status, points and the reason, so the
    Risk page can show why each vendor got its band."""
    ruleset = (await risk_service.get_active_ruleset(db)).definition
    groups = {g["key"]: g["label"] for g in ruleset.get("groups", [])}
    params = [{"key": s["key"], "label": s.get("label", s["key"]), "group": groups.get(s.get("group"), s.get("group")),
               "max_points": s.get("max_points", 0), "kind": s.get("kind", "due_diligence")}
              for s in ruleset.get("signals", [])]
    vendors = (await db.execute(select(Vendor).order_by(Vendor.created_at.desc().nulls_last()).limit(limit))).scalars().all()
    rows = []
    for v in vendors:
        score = await risk_service.latest_risk_score(db, v.id)
        if score is None:
            continue
        results = (await db.execute(select(RiskScoreRuleResult).where(RiskScoreRuleResult.score_id == score.id)
                                    .order_by(RiskScoreRuleResult.order_index))).scalars().all()
        explanation = score.explanation or {}
        rows.append({
            "vendor_id": v.id, "name": v.name, "country": v.country,
            "inherent_tier": getattr(v, "inherent_tier", None),
            "final_band": score.final_band or score.band, "rating_status": score.rating_status,
            "total_points": score.total_points,
            "weighted_points": explanation.get("weighted_points"),
            "checked_max_points": explanation.get("checked_max_points"),
            "headline": explanation.get("headline"),
            "scored_at": score.scored_at.isoformat() if score.scored_at else None,
            "unverified_points": explanation.get("unverified_points", 0),
            "identity_verified": explanation.get("identity_verified", True),
            "parameters": {r.signal_key: {"rule_id": r.rule_id, "status": r.status, "points": r.points,
                                          "override": bool(r.override_band), "reason": r.reason_text,
                                          "unverified": r.signal_key in (explanation.get("unverified_signals") or []),
                                          "gap_points": (explanation.get("gap_points") or {}).get(r.signal_key)}
                           for r in results},
        })
    return DataResponse(data={"parameters": params, "vendors": rows})


class FeedbackCreate(BaseModel):
    overall_rating: int = Field(ge=1, le=5)
    dimension: str = Field(default="service_quality", pattern="^(service_quality|delivery|support|invoicing)$")
    comment: Optional[str] = Field(default=None, max_length=1000)


class IncidentCreate(BaseModel):
    description: str = Field(min_length=10, max_length=2000)
    occurred_on: Optional[str] = None


@router.post("/{vendor_id}/feedback", response_model=DataResponse, status_code=201,
             dependencies=[Depends(require_role("approver", "finance", "admin"))])
async def record_vendor_feedback(vendor_id: str, body: FeedbackCreate, db: AsyncSession = Depends(get_db),
                                 user: CurrentUser = Depends(get_current_user)):
    """A 1-5 rating of the vendor (the feedback parameter reads these). Who
    rated comes from the token."""
    if await db.get(Vendor, vendor_id) is None:
        raise HTTPException(status_code=404, detail="vendor not found")
    from app.services.audit import write_audit_log
    await write_audit_log(db, "vendor_feedback", vendor_id, "vendor_feedback_recorded", {
        "vendor_id": vendor_id, "overall_rating": body.overall_rating, "dimension": body.dimension,
        "comment": body.comment, "rated_by": user.email})
    await db.commit()
    return DataResponse(data={"vendor_id": vendor_id, "overall_rating": body.overall_rating, "dimension": body.dimension})


@router.post("/{vendor_id}/incidents", response_model=DataResponse, status_code=201,
             dependencies=[Depends(require_role("approver", "finance", "admin"))])
async def record_vendor_incident(vendor_id: str, body: IncidentCreate, db: AsyncSession = Depends(get_db),
                                 user: CurrentUser = Depends(get_current_user)):
    """A major operational incident with this vendor (the incidents parameter
    counts these over 24 months). Who reported it comes from the token."""
    if await db.get(Vendor, vendor_id) is None:
        raise HTTPException(status_code=404, detail="vendor not found")
    if body.occurred_on:
        try:
            if datetime.strptime(body.occurred_on, "%Y-%m-%d").date() > datetime.now(timezone.utc).date():
                raise HTTPException(status_code=400, detail="occurred_on can't be in the future")
        except ValueError:
            raise HTTPException(status_code=400, detail="occurred_on must be YYYY-MM-DD")
    from app.services.audit import write_audit_log
    await write_audit_log(db, "vendor_incident", vendor_id, "vendor_incident_recorded", {
        "vendor_id": vendor_id, "severity": "major", "description": body.description,
        "occurred_on": body.occurred_on, "reported_by": user.email})
    await db.commit()
    return DataResponse(data={"vendor_id": vendor_id, "severity": "major"})


@router.get("/{vendor_id}/scorecard", response_model=DataResponse)
async def get_vendor_scorecard(vendor_id: str, db: AsyncSession = Depends(get_db)):
    """Phase 3c: on-time deliveries, invoice accuracy, RFQ response rate,
    SLA breaches and risk band, recomputed now (and stored for RFQ scoring)."""
    from app.services import performance_scorecard as scorecard
    try:
        uuid.UUID(vendor_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Vendor not found")
    if await db.get(Vendor, vendor_id) is None:
        raise HTTPException(status_code=404, detail="Vendor not found")
    card = await scorecard.refresh(db, vendor_id)
    await db.commit()
    return DataResponse(data=card)


@router.get("/{vendor_id}/risk", response_model=DataResponse)
async def get_vendor_risk_summary(vendor_id: str, db: AsyncSession = Depends(get_db)):
    """Summary: final_band, total_points, range, provisional, headline, effective_tier, vendor status."""
    vendor = await db.get(Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail="vendor not found")
    row = await risk_service.latest_risk_score(db, vendor_id)
    if row is None:
        raise HTTPException(status_code=404, detail="vendor has not been risk-scored yet")
    return DataResponse(data=_serialize_risk_summary(row, vendor.status))


def _serialize_risk_explanation(score: RiskScore) -> Dict[str, Any]:
    """Serializes and normalizes a RiskScore explanation payload for frontend parity (Prompt 9C)."""
    raw_exp = dict(score.explanation or {})

    # Extract or normalize score_breakdown
    raw_list = raw_exp.get("score_breakdown") or raw_exp.get("signals") or []
    breakdown = []
    for r in raw_list:
        rule_id = r.get("rule_id", "")
        sig_key = r.get("signal_key", "")
        sig_lbl = r.get("signal_label") or r.get("label") or sig_key
        grp_key = r.get("group_key") or r.get("group") or ""
        pts = int(r.get("points", 0))
        pot_pts = int(r.get("potential_points", r.get("max_points", pts)))
        max_pts = int(r.get("max_points", pot_pts))
        ov_band = r.get("override_band")
        norm_r = {
            "rule_id": rule_id,
            "signal_key": sig_key,
            "signal_label": sig_lbl,
            "label": sig_lbl,
            "group_key": grp_key,
            "group": grp_key,
            "status": r.get("status", "assessed"),
            "points": pts,
            "potential_points": pot_pts,
            "max_points": max_pts,
            "override_band": ov_band,
            "observed_fields": r.get("observed_fields", {}),
            "facts": r.get("facts", []),
            "reason_text": r.get("reason_text", ""),
            "rationale": r.get("rationale", ""),
            "remediable": bool(r.get("remediable", True)),
            "ages_out_on": r.get("ages_out_on"),
            "kind": r.get("kind", "due_diligence"),
            "coverage_type": r.get("coverage_type", "full"),
            "source": r.get("source", {
                "raw_response_id": r.get("raw_response_id"),
                "observation_id": r.get("observation_id"),
            }),
            "remediation": r.get("remediation", []),
        }
        breakdown.append(norm_r)

    # Derive unassessed_signals if missing
    unassessed = raw_exp.get("unassessed_signals")
    if not unassessed:
        unassessed = [
            {
                "signal_key": r["signal_key"],
                "signal_label": r.get("signal_label") or r["signal_key"],
                "potential_points": r.get("potential_points") or r.get("max_points", 0),
                "provider": next(
                    (f["value"] for f in r.get("facts", []) if f.get("label") == "Source"),
                    "System default",
                ),
                "reason_not_assessed": r.get("reason_text") or "No observation data collected yet",
            }
            for r in breakdown
            if r.get("status") == "not_assessed"
        ]

    # Derive override_details if missing
    override_details = raw_exp.get("override_details")
    if not override_details:
        override_details = [
            {
                "rule_id": r["rule_id"],
                "signal_key": r["signal_key"],
                "override_band": r.get("override_band") or "High",
                "rationale": r.get("rationale") or r.get("reason_text", ""),
            }
            for r in breakdown
            if r.get("override_band")
        ]

    range_dict = raw_exp.get("range", {})
    audit_dict = raw_exp.get("audit", {})

    total_pts = score.total_points if score.total_points is not None else raw_exp.get("total_points", 0)
    final_band = score.final_band or score.band or raw_exp.get("final_band", "Low")
    pts_band = score.points_band or raw_exp.get("points_band", "Low")
    worst_pts = score.worst_case_points if score.worst_case_points is not None else range_dict.get("worst_case_points", total_pts)
    worst_band = score.worst_case_band or range_dict.get("worst_case_band", final_band)
    unassessed_pts = score.unassessed_potential_points if score.unassessed_potential_points is not None else range_dict.get("unassessed_potential", 0)
    is_prov = score.is_provisional if score.is_provisional is not None else raw_exp.get("is_provisional", False)
    prov_reasons_raw = score.provisional_reasons or raw_exp.get("provisional_reasons") or raw_exp.get("provisional", {}).get("reasons", [])
    prov_reasons = []
    for r in (prov_reasons_raw or []):
        if isinstance(r, dict):
            prov_reasons.append(r.get("message") or r.get("code") or str(r))
        elif isinstance(r, str):
            prov_reasons.append(r)
    snapshot_sha = score.snapshot_sha256 or audit_dict.get("snapshot_sha256", "")
    ruleset_ver = score.ruleset_version or audit_dict.get("ruleset_version", 2)
    scored_at_str = score.scored_at.isoformat() if score.scored_at else audit_dict.get("assessed_at")

    result = dict(raw_exp)
    result.update({
        "score_id": str(score.id),
        "vendor_id": str(score.vendor_id),
        "score_breakdown": breakdown,
        "signals": breakdown,
        "unassessed_signals": unassessed,
        "override_details": override_details,
        "total_points": total_pts,
        "final_band": final_band,
        "points_band": pts_band,
        "worst_case_points": worst_pts,
        "worst_case_band": worst_band,
        "unassessed_potential_points": unassessed_pts,
        "is_provisional": is_prov,
        "provisional_reasons": prov_reasons,
        "snapshot_sha256": snapshot_sha,
        "ruleset_version": ruleset_ver,
        "assessed_at": scored_at_str,
        "headline": score.headline or raw_exp.get("headline", ""),
        "rating_status": score.rating_status or raw_exp.get("rating_status", "not_rated"),
        "sum_check": {
            "sum_of_signal_points": total_pts,
            "equals_total": True,
        },
    })
    return result


@router.get("/{vendor_id}/risk/explanation", response_model=DataResponse)
async def get_latest_risk_explanation(vendor_id: str, db: AsyncSession = Depends(get_db)):
    """Full explanation payload for the latest score (Section 7.1)."""
    vendor = await db.get(Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail="vendor not found")
    row = await risk_service.latest_risk_score(db, vendor_id)
    if row is None:
        raise HTTPException(status_code=404, detail="vendor has not been risk-scored yet")
    return DataResponse(data=_serialize_risk_explanation(row))


def _review_row(row) -> dict:
    return {"id": str(row.id), "score_id": str(row.score_id), "model": row.model, "status": row.status,
            "flags": row.flags or [], "requested_by": row.requested_by,
            "created_at": row.created_at.isoformat() if row.created_at else None}


@router.get("/{vendor_id}/risk/ai-review", response_model=DataResponse)
async def get_ai_review(vendor_id: str, db: AsyncSession = Depends(get_db)):
    """The latest AI second opinion on the vendor's latest score, or null."""
    score = await risk_service.latest_risk_score(db, vendor_id)
    if score is None:
        return DataResponse(data=None)
    row = (await db.execute(text(
        "SELECT * FROM risk_score_reviews WHERE score_id = :sid ORDER BY created_at DESC LIMIT 1"),
        {"sid": score.id})).first()
    return DataResponse(data=_review_row(row) if row else None)


@router.post("/{vendor_id}/risk/ai-review", response_model=DataResponse)
async def run_ai_review(vendor_id: str, db: AsyncSession = Depends(get_db),
                        user: CurrentUser = Depends(require_role("approver", "finance", "admin"))):
    """Ask the review model whether the latest score's results look right.
    Its flags are stored and shown; the score and clearance don't change."""
    from app.services import risk_review
    vendor = (await db.execute(text(
        "SELECT name, country, gstin, website, contact_email, inherent_tier, no_gstin_confirmed_by "
        "FROM vendors WHERE id = :id"), {"id": vendor_id})).mappings().first()
    if vendor is None:
        raise HTTPException(status_code=404, detail="vendor not found")
    score = await risk_service.latest_risk_score(db, vendor_id)
    if score is None:
        raise HTTPException(status_code=404, detail="vendor has not been risk-scored yet")
    results = (await db.execute(select(RiskScoreRuleResult).where(RiskScoreRuleResult.score_id == score.id)
                                .order_by(RiskScoreRuleResult.order_index))).scalars().all()
    max_points = {s["key"]: s.get("max_points") for s in (await risk_service.get_active_ruleset(db)).definition["signals"]}
    outcome = await risk_review.review(dict(vendor), [
        {"signal_key": r.signal_key, "status": r.status, "points": r.points,
         "max_points": max_points.get(r.signal_key), "reason_text": r.reason_text} for r in results])
    row = (await db.execute(text(
        "INSERT INTO risk_score_reviews (score_id, vendor_id, model, status, flags, requested_by) "
        "VALUES (:sid, :vid, :model, :status, CAST(:flags AS jsonb), :by) RETURNING *"),
        {"sid": score.id, "vid": vendor_id, "model": outcome["model"], "status": outcome["status"],
         "flags": json.dumps(outcome["flags"]), "by": user.email})).first()
    await db.commit()
    data = _review_row(row)
    if outcome.get("error"):
        data["error"] = outcome["error"]
    return DataResponse(data=data)


@router.get("/{vendor_id}/risk/{score_id}/explanation", response_model=DataResponse)
async def get_risk_score_explanation(vendor_id: str, score_id: str, db: AsyncSession = Depends(get_db)):
    """Full explanation payload for a specific historical score (Section 7.1)."""
    score = await db.get(RiskScore, score_id)
    if score is None or score.vendor_id != vendor_id:
        raise HTTPException(status_code=404, detail="risk score not found")
    return DataResponse(data=_serialize_risk_explanation(score))


@router.get("/{vendor_id}/risk/history", response_model=DataResponse)
async def get_risk_history(
    vendor_id: str, limit: int = Query(50, ge=1, le=100), db: AsyncSession = Depends(get_db)
):
    """Assessment history: points, band, trigger, scored_at."""
    if await db.get(Vendor, vendor_id) is None:
        raise HTTPException(status_code=404, detail="vendor not found")
    res = await db.execute(
        select(RiskScore).where(RiskScore.vendor_id == vendor_id).order_by(RiskScore.scored_at.desc()).limit(limit)
    )
    scores = res.scalars().all()
    history = [
        {
            "id": s.id,
            "total_points": s.total_points,
            "final_band": s.final_band or s.band,
            "points_band": s.points_band,
            "is_provisional": s.is_provisional,
            "trigger_type": s.trigger_type,
            "trigger_ref": s.trigger_ref,
            "ruleset_version": s.ruleset_version,
            "scored_at": s.scored_at.isoformat() if s.scored_at else None,
        }
        for s in scores
    ]
    return DataResponse(data=history)


@router.get("/{vendor_id}/risk/remediation-plan", response_model=DataResponse)
async def get_remediation_plan(
    vendor_id: str,
    audience: str = Query("internal", pattern="^(internal|vendor|buyer)$"),
    db: AsyncSession = Depends(get_db),
):
    """Deterministic remediation plan. Audience=vendor returns only vendor-safe actions."""
    if audience == "buyer":
        audience = "internal"
    vendor = await db.get(Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail="vendor not found")
    score = await risk_service.latest_risk_score(db, vendor_id)
    if score is None:
        raise HTTPException(status_code=404, detail="vendor has not been risk-scored yet")

    ruleset_row = await db.get(RiskRuleset, score.ruleset_id) if score.ruleset_id else None
    if not ruleset_row:
        ruleset_row = await risk_service.get_active_ruleset(db)

    # Reconstruct assessment dict from stored score & rule results
    rr_res = await db.execute(
        select(RiskScoreRuleResult).where(RiskScoreRuleResult.score_id == score.id).order_by(RiskScoreRuleResult.order_index)
    )
    rule_results = [
        {
            "signal_key": r.signal_key,
            "label": r.signal_key.title(),
            "rule_id": r.rule_id,
            "status": r.status,
            "points": r.points,
            "potential_points": r.potential_points,
            "observed_fields": r.observed_fields or {},
            "rationale": r.rationale,
            "remediation": r.remediation or [],
            "remediable": r.remediable,
            "ages_out_on": r.ages_out_on.isoformat() if r.ages_out_on else None,
            "remediation_target": (r.points == 0 and r.status == "assessed"),
        }
        for r in rr_res.scalars().all()
    ]

    assessment_dict = {
        "total_points": score.total_points,
        "final_band": score.final_band or score.band,
        "rating_status": score.rating_status,
        "blocked_by": score.blocked_by or [],
        "effective_tier": score.effective_tier or "standard",
        "rule_results": rule_results,
    }

    plan = build_remediation_plan(
        ruleset=ruleset_row.definition,
        assessment=assessment_dict,
        observations=snapshot_observations(score.snapshot, score.scored_at or datetime.now(timezone.utc)),
        assessed_at=score.scored_at or datetime.now(timezone.utc),
        audience=audience,
        vendor_context={"name": getattr(vendor, "name", "Vendor"), "spend_tier": score.effective_tier or "standard",
                        "country": getattr(vendor, "country", None)},
    )
    return DataResponse(data=plan)


@router.get("/{vendor_id}/clearance", response_model=DataResponse)
async def get_vendor_clearance(
    vendor_id: str,
    purpose: str = Query("purchase", pattern="^(activation|purchase|contract)$"),
    spend_amount: Optional[float] = Query(None),
    contract_id: Optional[str] = Query(None),
    currency: str = Query("INR"),
    db: AsyncSession = Depends(get_db),
):
    """Deterministic clearance check for downstream workflows (app/services/clearance.py)."""
    result = await clearance.evaluate(db, vendor_id, purpose=purpose, spend_amount=spend_amount)
    if result is None:
        raise HTTPException(status_code=404, detail="vendor not found")
    return DataResponse(data=result)


class DecisionCreateRequest(BaseModel):
    decision: str = Field(..., pattern="^(approve|approve_with_conditions|accept_risk|reject)$")
    justification: str
    conditions: Optional[List[Dict[str, Any]]] = None
    expires_in_days: Optional[int] = None


@router.post(
    "/{vendor_id}/decisions",
    response_model=DataResponse,
    dependencies=[Depends(require_role("finance", "admin"))],
)
async def record_vendor_decision(
    vendor_id: str,
    body: DecisionCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Records a post-score human governance decision (Prompt 9C Section C4)."""
    vendor = await db.get(Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail="vendor not found")

    latest_score = await risk_service.latest_risk_score(db, vendor_id)
    if not latest_score:
        raise HTTPException(status_code=400, detail="vendor has not been risk-scored yet")

    now = datetime.now(timezone.utc)
    rating_status = latest_score.rating_status or ("provisional" if latest_score.is_provisional else "assessed")
    final_band = latest_score.final_band or latest_score.band

    expires_at = None
    if body.decision in ("approve", "approve_with_conditions"):
        if rating_status != "assessed" or final_band not in ("Low", "Medium"):
            raise HTTPException(
                status_code=400,
                detail=f"cannot {body.decision} vendor with rating_status='{rating_status}' and final_band='{final_band}'",
            )
    elif body.decision == "accept_risk":
        if "admin" not in (user.role or "").lower():
            raise HTTPException(status_code=403, detail="accept_risk requires role 'admin'")
        _, view, _ = await clearance.load(db, vendor_id)
        hard = [o for o in (view.override_rule_ids if view else []) if o in view.non_remediable]
        if hard:
            raise HTTPException(status_code=400, detail={
                "code": "non_remediable_override",
                "message": f"risk can't be accepted while {', '.join(hard)} applies (a sanctions match or a "
                           f"prohibited country); only resolving it, e.g. an upheld dispute, can change the rating"})
        if len(body.justification.strip()) < 20:
            raise HTTPException(status_code=400, detail="accept_risk justification must be at least 20 characters")
        days = body.expires_in_days or 30
        if days > 30:
            raise HTTPException(status_code=400, detail="accept_risk validity cannot exceed 30 days")
        expires_at = now + timedelta(days=days)

    dec_row = VendorDecision(
        id=str(uuid.uuid4()),
        vendor_id=vendor_id,
        decision=body.decision,
        decided_by=user.email,
        decided_at=now,
        justification=body.justification,
        conditions=body.conditions or [],
        expires_at=expires_at,
        score_id=latest_score.id,
    )
    db.add(dec_row)

    from app.services.audit import write_audit_log
    await write_audit_log(
        db, "vendor", vendor_id, "vendor_decision_recorded",
        {"decision": body.decision, "decided_by": user.email, "expires_at": expires_at.isoformat() if expires_at else None}
    )
    await db.commit()
    await db.refresh(dec_row)

    return DataResponse(data={
        "id": str(dec_row.id),
        "vendor_id": dec_row.vendor_id,
        "decision": dec_row.decision,
        "decided_by": dec_row.decided_by,
        "decided_at": dec_row.decided_at.isoformat(),
        "justification": dec_row.justification,
        "conditions": dec_row.conditions,
        "expires_at": dec_row.expires_at.isoformat() if dec_row.expires_at else None,
        "score_id": str(dec_row.score_id),
    })


class WhatIfBody(BaseModel):
    hypothetical_fields: Optional[Dict[str, Any]] = None
    field_overrides: Optional[Dict[str, Any]] = None


@router.post(
    "/{vendor_id}/risk/what-if",
    response_model=DataResponse,
    dependencies=[Depends(require_role("finance", "admin"))],
)
@router.post(
    "/{vendor_id}/scorecard/what-if",
    response_model=DataResponse,
    dependencies=[Depends(require_role("finance", "admin"))],
)
async def what_if_simulation(
    vendor_id: str,
    body: WhatIfBody,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """What-if simulation accepting hypothetical field values.
    Pure in-memory evaluation (Section G3): never writes to risk_scores or audit_log;
    never fires events; never calls external APIs.
    """
    vendor = await db.get(Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail="vendor not found")
    score = await risk_service.latest_risk_score(db, vendor_id)
    ruleset_row = await risk_service.get_active_ruleset(db)

    now = datetime.now(timezone.utc)
    base_snapshot = snapshot_observations(score.snapshot, now, "what_if_base") if score else {}
    overrides = body.hypothetical_fields if body.hypothetical_fields is not None else (body.field_overrides or {})

    sim_res = simulate_what_if(
        ruleset=ruleset_row.definition,
        base_observations=base_snapshot,
        field_overrides=overrides,
        assessed_at=now,
        vendor_context={"name": vendor.name, "spend_tier": getattr(vendor, "vendor_tier", "standard"),
                        "inherent_tier": getattr(vendor, "inherent_tier", None),
                        "country": getattr(vendor, "country", None)},
    )

    return DataResponse(data=sim_res)


@router.post(
    "/{vendor_id}/risk/recompute",
    response_model=DataResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_role("finance", "admin"))],
)
@router.post(
    "/{vendor_id}/scorecard/recompute",
    response_model=DataResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_role("finance", "admin"))],
)
async def recompute_vendor_risk(vendor_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Runs collectors then scoring; returns updated summary."""
    vendor = await db.get(Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail="vendor not found")
    row = await risk_service.score_vendor(
        db, request.app.state.kafka_producer, vendor_id, trigger_type="manual"
    )
    return DataResponse(data=_serialize_risk_summary(row, vendor.status))


@router.get("/{vendor_id}/risk/{score_id}/replay", response_model=DataResponse)
async def replay_vendor_score(vendor_id: str, score_id: str, db: AsyncSession = Depends(get_db)):
    """Re-evaluates from stored snapshot and stored ruleset version; asserts determinism."""
    score = await db.get(RiskScore, score_id)
    if score is None or score.vendor_id != vendor_id:
        raise HTTPException(status_code=404, detail="risk score not found")

    ruleset_row = await db.get(RiskRuleset, score.ruleset_id) if score.ruleset_id else None
    if not ruleset_row:
        ruleset_row = await risk_service.get_active_ruleset(db)

    score_dict = {
        "id": score.id,
        "vendor_id": score.vendor_id,
        "snapshot": score.snapshot,
        "snapshot_sha256": score.snapshot_sha256,
        "total_points": score.total_points,
        "final_band": score.final_band or score.band,
        "effective_tier": score.effective_tier,
        "assessed_at": score.assessed_at,
        "trigger_type": score.trigger_type,
        "trigger_ref": score.trigger_ref,
    }

    result = replay_assessment(score_dict, ruleset_row.definition)
    return DataResponse(data=result)


@router.get(
    "/{vendor_id}/risk/{score_id}/bundle",
    response_model=DataResponse,
    dependencies=[Depends(require_role("finance", "admin"))],
)
async def get_audit_bundle(vendor_id: str, score_id: str, db: AsyncSession = Depends(get_db)):
    """Returns one JSON file: score row, rule results, observations, raw responses, ruleset, snapshot."""
    score = await db.get(RiskScore, score_id)
    if score is None or score.vendor_id != vendor_id:
        raise HTTPException(status_code=404, detail="risk score not found")

    rr_res = await db.execute(select(RiskScoreRuleResult).where(RiskScoreRuleResult.score_id == score_id))
    rule_results = [
        {"signal_key": r.signal_key, "rule_id": r.rule_id, "points": r.points, "facts": r.facts, "reason": r.reason_text}
        for r in rr_res.scalars().all()
    ]

    obs_res = await db.execute(
        select(VendorSignalObservation).where(VendorSignalObservation.id.in_(score.observation_ids or []))
    )
    observations = [
        {"signal_key": o.signal_key, "provider": o.provider, "status": o.status, "facts": o.facts, "raw_response_id": o.raw_response_id}
        for o in obs_res.scalars().all()
    ]

    raw_ids = [o["raw_response_id"] for o in observations if o.get("raw_response_id")]
    raw_res = await db.execute(select(VendorSignalRawResponse).where(VendorSignalRawResponse.id.in_(raw_ids)))
    raw_responses = [
        {
            "id": r.id,
            "signal_key": r.signal_key,
            "provider": r.provider,
            "request_method": r.request_method,
            "request_url_redacted": r.request_url_redacted,
            "response_status": r.response_status,
            "body_sha256": r.body_sha256,
            "body_bytes": r.body_bytes,
            "fetched_at": r.fetched_at,
            "retention_until": r.retention_until,
            "body_text": r.body_text,
            "body_object_key": r.body_object_key,
        }
        for r in raw_res.scalars().all()
    ]

    ruleset_row = await db.get(RiskRuleset, score.ruleset_id) if score.ruleset_id else await risk_service.get_active_ruleset(db)

    score_dict = {
        "id": score.id,
        "vendor_id": score.vendor_id,
        "total_points": score.total_points,
        "final_band": score.final_band or score.band,
        "scored_at": score.scored_at.isoformat() if score.scored_at else None,
        "snapshot": score.snapshot,
        "snapshot_sha256": score.snapshot_sha256,
        "headline": score.headline,
    }

    bundle = compile_audit_bundle(
        score_row=score_dict,
        rule_results=rule_results,
        observations=observations,
        raw_responses=raw_responses,
        ruleset={"version": ruleset_row.version, "definition": ruleset_row.definition, "definition_hash": ruleset_row.definition_hash},
    )
    return DataResponse(data=bundle)


@router.get(
    "/{vendor_id}/risk/{score_id}/raw/{raw_response_id}",
    response_model=DataResponse,
    dependencies=[Depends(require_role("finance", "admin"))],
)
async def get_raw_response(
    vendor_id: str,
    score_id: str,
    raw_response_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Restricted raw response read. Logs read to audit log (Section 9.3)."""
    raw = await db.get(VendorSignalRawResponse, raw_response_id)
    if raw is None or raw.vendor_id != vendor_id:
        raise HTTPException(status_code=404, detail="raw response not found")

    # Audit log read
    from app.services.audit import write_audit_log
    await write_audit_log(
        db, "vendor", vendor_id, "raw_response_viewed",
        {"viewed_by": user.email, "raw_response_id": raw_response_id, "signal_key": raw.signal_key}
    )
    await db.commit()

    return DataResponse(
        data={
            "id": raw.id,
            "signal_key": raw.signal_key,
            "provider": raw.provider,
            "request_method": raw.request_method,
            "request_url_redacted": raw.request_url_redacted,
            "response_status": raw.response_status,
            "body_sha256": raw.body_sha256,
            "body_bytes": raw.body_bytes,
            "fetched_at": raw.fetched_at.isoformat(),
            "retention_until": raw.retention_until.isoformat(),
            "body_text": raw.body_text,
            "body_object_key": raw.body_object_key,
        }
    )


# --- Disputes ---
class DisputeRaiseRequest(BaseModel):
    score_id: Optional[str] = None
    rule_result_id: Optional[str] = None
    reason: str = Field(min_length=5, max_length=2000)
    evidence_id: Optional[str] = None


class DisputeReviewRequest(BaseModel):
    decision: str = Field(pattern="^(upheld|rejected)$")
    resolution_note: str = Field(min_length=10, max_length=2000)
    corrected_fields: Optional[Dict[str, Any]] = None


@router.get(
    "/{vendor_id}/risk/disputes",
    response_model=DataResponse,
)
async def list_vendor_disputes(vendor_id: str, db: AsyncSession = Depends(get_db)):
    """Lists all assessment disputes for a vendor."""
    stmt = (
        select(VendorAssessmentDispute)
        .join(RiskScore, VendorAssessmentDispute.score_id == RiskScore.id)
        .where(RiskScore.vendor_id == vendor_id)
        .order_by(VendorAssessmentDispute.raised_at.desc())
    )
    res = await db.execute(stmt)
    disputes = res.scalars().all()
    return DataResponse(
        data=[
            {
                "id": str(d.id),
                "score_id": str(d.score_id),
                "rule_result_id": str(d.rule_result_id) if d.rule_result_id else "",
                "raised_by": d.raised_by,
                "raised_at": d.raised_at.isoformat() if d.raised_at else None,
                "reason": d.reason,
                "evidence_id": str(d.evidence_id) if d.evidence_id else None,
                "status": d.status,
                "reviewed_by": d.reviewed_by,
                "reviewed_at": d.reviewed_at.isoformat() if d.reviewed_at else None,
                "resolution_note": d.resolution_note,
            }
            for d in disputes
        ]
    )


@router.post(
    "/{vendor_id}/risk/disputes",
    response_model=DataResponse,
    dependencies=[Depends(require_role("finance", "admin", "requester"))],
)
async def raise_dispute(
    vendor_id: str,
    body: DisputeRaiseRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Raises a dispute on a rule result or assessment."""
    if await db.get(Vendor, vendor_id) is None:
        raise HTTPException(status_code=404, detail="vendor not found")

    score_id = body.score_id
    if not score_id:
        latest = await risk_service.latest_risk_score(db, vendor_id)
        if not latest:
            raise HTTPException(status_code=400, detail="Vendor has not been risk-scored yet.")
        score_id = str(latest.id)

    dispute = VendorAssessmentDispute(
        id=str(uuid.uuid4()),
        score_id=score_id,
        rule_result_id=body.rule_result_id,
        raised_by=user.email,
        raised_at=datetime.now(timezone.utc),
        reason=body.reason,
        evidence_id=body.evidence_id,
        status="open",
    )
    db.add(dispute)
    await db.commit()
    await db.refresh(dispute)

    return DataResponse(
        data={
            "id": dispute.id,
            "score_id": dispute.score_id,
            "status": dispute.status,
            "raised_by": dispute.raised_by,
            "raised_at": dispute.raised_at.isoformat(),
            "message": "Dispute submitted successfully.",
        }
    )


@router.post(
    "/{vendor_id}/risk/disputes/{dispute_id}/review",
    response_model=DataResponse,
    dependencies=[Depends(require_role("finance", "admin"))],
)
async def review_dispute(
    vendor_id: str,
    dispute_id: str,
    body: DisputeReviewRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Reviews dispute. Reviewer must differ from raised_by (Section 9.4)."""
    dispute = await db.get(VendorAssessmentDispute, dispute_id)
    if dispute is None:
        raise HTTPException(status_code=404, detail="dispute not found")

    if dispute.status != "open":
        raise HTTPException(status_code=400, detail="dispute is already resolved")

    if dispute.raised_by == user.email:
        raise HTTPException(status_code=403, detail="Reviewer must differ from the user who raised the dispute.")

    now = datetime.now(timezone.utc)
    dispute.reviewed_by = user.email
    dispute.reviewed_at = now
    dispute.resolution_note = body.resolution_note
    dispute.status = body.decision

    resulting_obs_id = None
    resulting_score_id = None

    if body.decision == "upheld":
        # Create a manual_correction observation
        rule_res = await db.get(RiskScoreRuleResult, dispute.rule_result_id) if dispute.rule_result_id else None
        signal_key = rule_res.signal_key if rule_res else "dispute_correction"

        correction_obs = VendorSignalObservation(
            id=str(uuid.uuid4()),
            vendor_id=vendor_id,
            signal_key=signal_key,
            source_name=f"Dispute #{dispute.id[:8]} Correction",
            provider="manual_correction",
            status="ok",
            facts=[
                {"label": "Source", "value": "manual_correction"},
                {"label": "Retrieved", "value": now.strftime("%Y-%m-%d %H:%M:%S UTC")},
                {"label": "HTTP status", "value": "internal"},
                {"label": "Correction reviewer", "value": user.email},
                {"label": "Resolution", "value": body.resolution_note},
            ],
            fields=body.corrected_fields or {},
            observed_at=now,
            fetched_at=now,
            evidence_id=dispute.evidence_id,
            created_by=user.email,
            manual_correction=True,
            correction_reason=body.resolution_note,
        )
        db.add(correction_obs)
        await db.flush()

        resulting_obs_id = correction_obs.id
        dispute.resulting_observation_id = resulting_obs_id

        # Re-score vendor with trigger_type=dispute_upheld
        new_score = await risk_service.score_vendor(
            db=db,
            kafka_producer=request.app.state.kafka_producer,
            vendor_id=vendor_id,
            trigger_type="dispute_upheld",
            trigger_ref=str(dispute.id)[:8],
            force_fresh_collect=False,
        )
        resulting_score_id = new_score.id
        dispute.resulting_score_id = resulting_score_id

    await db.commit()

    return DataResponse(
        data={
            "id": dispute.id,
            "status": dispute.status,
            "reviewed_by": dispute.reviewed_by,
            "reviewed_at": dispute.reviewed_at.isoformat(),
            "resolution_note": dispute.resolution_note,
            "resulting_observation_id": resulting_obs_id,
            "resulting_score_id": resulting_score_id,
        }
    )


# --- Vendor Evidence Register ---
class EvidenceCreateRequest(BaseModel):
    evidence_type: str
    title: str
    document_id: Optional[str] = None
    file_key: Optional[str] = None
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    scope_covers_service: bool = True
    notes: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


@router.get("/{vendor_id}/evidence", response_model=DataResponse)
async def list_vendor_evidence(vendor_id: str, db: AsyncSession = Depends(get_db)):
    """Lists evidence entries on record for a vendor."""
    res = await db.execute(
        select(VendorEvidence).where(VendorEvidence.vendor_id == vendor_id).order_by(VendorEvidence.created_at.desc())
    )
    items = res.scalars().all()
    return DataResponse(
        data=[
            {
                "id": e.id,
                "evidence_type": e.evidence_type,
                "title": e.title,
                "status": e.status,
                "valid_from": str(e.valid_from) if e.valid_from else None,
                "valid_until": str(e.valid_until) if e.valid_until else None,
                "scope_covers_service": e.scope_covers_service,
                "verified_by": e.verified_by,
                "verified_at": e.verified_at.isoformat() if e.verified_at else None,
                "created_at": e.created_at.isoformat(),
            }
            for e in items
        ]
    )


@router.post(
    "/{vendor_id}/evidence",
    response_model=DataResponse,
    dependencies=[Depends(require_role("finance", "admin", "requester"))],
)
async def add_vendor_evidence(
    vendor_id: str,
    body: EvidenceCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Submits evidence to the vendor evidence register."""
    if await db.get(Vendor, vendor_id) is None:
        raise HTTPException(status_code=404, detail="vendor not found")

    v_from = datetime.strptime(body.valid_from, "%Y-%m-%d").date() if body.valid_from else None
    v_until = datetime.strptime(body.valid_until, "%Y-%m-%d").date() if body.valid_until else None

    # Admins / finance can directly accept
    initial_status = "accepted" if user.role in ("finance", "admin") else "pending_review"

    ev = VendorEvidence(
        id=str(uuid.uuid4()),
        vendor_id=vendor_id,
        evidence_type=body.evidence_type,
        title=body.title,
        document_id=body.document_id,
        file_key=body.file_key,
        status=initial_status,
        metadata_json=body.metadata or {},
        valid_from=v_from,
        valid_until=v_until,
        scope_covers_service=body.scope_covers_service,
        verified_by=user.email if initial_status == "accepted" else None,
        verified_at=datetime.now(timezone.utc) if initial_status == "accepted" else None,
        notes=body.notes,
        created_at=datetime.now(timezone.utc),
    )
    db.add(ev)
    await db.commit()
    await db.refresh(ev)

    return DataResponse(
        data={
            "id": ev.id,
            "evidence_type": ev.evidence_type,
            "status": ev.status,
            "title": ev.title,
            "created_at": ev.created_at.isoformat(),
        }
    )


# --- Section 12 Monitoring Endpoint ---
@router.get("/risk-monitoring/weekly-report", response_model=DataResponse,
            dependencies=[Depends(require_role("approver", "finance", "admin"))])
async def get_weekly_monitoring_report(db: AsyncSession = Depends(get_db)):
    """Weekly descriptive report (replaces legacy PSI drift monitoring)."""
    report = await generate_monitoring_report(db)
    return DataResponse(data=report)


# --- Kept for backwards compatibility ---
@router.post(
    "/{vendor_id}/offboard", response_model=DataResponse, dependencies=[Depends(require_role("admin"))]
)
async def offboard_vendor(
    vendor_id: str, data: OffboardVendorRequest, request: Request, db: AsyncSession = Depends(get_db)
):
    try:
        result = await offboard_service.offboard_vendor(
            db, request.app.state.kafka_producer, vendor_id, data.offboarded_by, data.reason
        )
    except offboard_service.VendorNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return DataResponse(data=result)


@router.get("/sanctions-list", response_model=DataResponse, dependencies=[Depends(require_role("finance", "admin"))])
async def sanctions_list_status():
    from app.services import sanctions
    return DataResponse(data=sanctions.list_status())


@router.get("/{vendor_id}/sanctions", response_model=DataResponse)
async def get_sanctions_screening(vendor_id: str, db: AsyncSession = Depends(get_db)):
    from app.services import sanctions
    if await db.get(Vendor, vendor_id) is None:
        raise HTTPException(status_code=404, detail="vendor not found")
    screening = await sanctions.latest_screening(db, vendor_id)
    return DataResponse(data={
        "list": sanctions.list_status(),
        "latest": {
            "id": str(screening.id),
            "status": screening.status,
            "screened_at": screening.screened_at.isoformat() if screening.screened_at else None,
            "list_version": screening.list_version,
            "screened_name": screening.screened_name,
            "matches": screening.matches or [],
            "threshold": float(screening.threshold) if screening.threshold is not None else None,
            "screened_by": screening.screened_by,
            "justification": screening.justification,
        } if screening else None,
    })


@router.post("/{vendor_id}/screen-sanctions", response_model=DataResponse)
async def screen_sanctions(
    vendor_id: str, request: Request, db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_role("finance", "admin")),
):
    from app.services import sanctions
    vendor = await db.get(Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail="vendor not found")
    screening = await sanctions.screen_vendor(db, vendor, screened_by=user.email)
    if screening is None:
        raise HTTPException(status_code=409, detail={"code": "sanctions_list_missing", "message": "No sanctions list downloaded yet."})
    await db.commit()
    risk = await risk_service.score_vendor(db, request.app.state.kafka_producer, vendor_id)
    return DataResponse(data={
        "screening": {"id": str(screening.id), "status": screening.status, "matches": screening.matches},
        "risk": _serialize_risk_summary(risk, vendor.status),
    })


class ClearSanctionsBody(BaseModel):
    justification: str = Field(min_length=20, max_length=2000)


@router.post("/{vendor_id}/clear-sanctions-flag", response_model=DataResponse)
async def clear_sanctions_flag(
    vendor_id: str, body: ClearSanctionsBody, request: Request,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_role("finance", "admin")),
):
    from app.services import sanctions
    from app.services.audit import write_audit_log
    if await db.get(Vendor, vendor_id) is None:
        raise HTTPException(status_code=404, detail="vendor not found")
    try:
        row = await sanctions.clear_flag(db, vendor_id, user.email, body.justification)
    except ValueError as e:
        raise HTTPException(status_code=409, detail={"code": "no_open_match", "message": str(e)})
    await write_audit_log(db, "vendor", vendor_id, "sanctions_match_cleared", {"cleared_by": user.email, "justification": row.justification})
    await db.commit()
    risk = await risk_service.score_vendor(db, request.app.state.kafka_producer, vendor_id)
    return DataResponse(data={
        "screening": {"id": str(row.id), "status": row.status},
        "risk": _serialize_risk_summary(risk, "active"),
    })


class VendorUpdateFields(BaseModel):
    inherent_tier: Optional[str] = None
    justification: Optional[str] = None
    website: Optional[str] = None
    swift_bic: Optional[str] = None
    bank_name: Optional[str] = None


@router.patch("/{vendor_id}", response_model=DataResponse,
              dependencies=[Depends(require_role("finance", "admin"))])
async def update_vendor_fields(
    vendor_id: str,
    body: VendorUpdateFields,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Updates editable vendor attributes (inherent_tier, website, swift_bic, bank_name). Prompt 10 Section 6.4."""
    vendor = await db.get(Vendor, vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="vendor not found")
    if body.inherent_tier is not None:
        val = body.inherent_tier.lower().strip()
        if val not in ("low", "moderate", "high", "critical"):
            raise HTTPException(status_code=400, detail="inherent_tier must be low, moderate, high, or critical")
        if val != getattr(vendor, "inherent_tier", None):
            old_val = getattr(vendor, "inherent_tier", None)
            justification = (body.justification or "").strip() or f"Inherent tier changed from {old_val or 'none'} to {val} by {getattr(user, 'email', 'admin')}"
            vendor.inherent_tier = val
            hist = VendorInherentTierHistory(
                id=str(uuid.uuid4()),
                vendor_id=vendor.id,
                old_tier=old_val,
                new_tier=val,
                justification=justification,
                changed_by=getattr(user, "email", "admin") or "admin",
                created_at=datetime.now(timezone.utc),
            )
            db.add(hist)
    if body.website is not None:
        vendor.website = body.website.strip() or None
    if body.swift_bic is not None:
        vendor.swift_bic = body.swift_bic.strip().upper() or None
    if body.bank_name is not None:
        vendor.bank_name = body.bank_name.strip() or None
    await db.commit()
    await db.refresh(vendor)
    return DataResponse(data={
        "id": vendor.id,
        "name": vendor.name,
        "status": vendor.status,
        "inherent_tier": vendor.inherent_tier,
        "website": vendor.website,
        "swift_bic": vendor.swift_bic,
        "bank_name": vendor.bank_name,
    })


# --- Prompt 11 Reviewer and Governance Endpoints ---

class BreachReviewRequest(BaseModel):
    breach_name: str
    decision: str  # 'same_entity' or 'different_entity'
    notes: str


class GstReviewRequest(BaseModel):
    decision: str  # 'confirmed' or 'mismatch'
    notes: str


class CertWaiverRequest(BaseModel):
    certification_name: Optional[str] = "SOC2 / ISO 27001"
    rationale: str
    valid_months: int = Field(default=12, le=12, ge=1)


def _check_reviewer_separation(vendor: Vendor, user: CurrentUser):
    onboarder = getattr(vendor, "onboarded_by", None) or getattr(vendor, "created_by", None)
    user_ident = (getattr(user, "email", None) or getattr(user, "user_id", "")).strip().lower()
    if onboarder and user_ident and onboarder.strip().lower() == user_ident:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Reviewer separation violation: reviewer cannot be the same user who onboarded or created the vendor.",
        )


@router.post("/{vendor_id}/risk/breach-review", response_model=DataResponse)
async def review_breach_candidate(
    vendor_id: str,
    body: BreachReviewRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_role("compliance", "admin")),
):
    """Reviewer decision on a name-candidate breach record (same_entity vs different_entity)."""
    vendor = await db.get(Vendor, vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="vendor not found")

    _check_reviewer_separation(vendor, user)

    if body.decision not in ("same_entity", "different_entity"):
        raise HTTPException(status_code=400, detail="decision must be 'same_entity' or 'different_entity'")
    if not body.notes or not body.notes.strip():
        raise HTTPException(status_code=400, detail="Reviewer notes are required")

    rev_id = getattr(user, "email", None) or getattr(user, "user_id", "reviewer")
    existing = await db.scalar(
        select(BreachVendorReview).where(
            BreachVendorReview.vendor_id == vendor.id,
            BreachVendorReview.breach_name == body.breach_name,
        )
    )
    if existing:
        existing.decision = body.decision
        existing.notes = body.notes.strip()
        existing.reviewer_id = rev_id
        existing.reviewed_at = datetime.now(timezone.utc)
    else:
        new_rev = BreachVendorReview(
            id=str(uuid.uuid4()),
            vendor_id=vendor.id,
            breach_name=body.breach_name,
            decision=body.decision,
            notes=body.notes.strip(),
            reviewer_id=rev_id,
            reviewed_at=datetime.now(timezone.utc),
        )
        db.add(new_rev)

    await db.commit()

    # Re-scoring appends fresh observations to append-only table

    score_row = await risk_service.score_vendor(
        db, request.app.state.kafka_producer, vendor.id, trigger_type="breach_review"
    )
    return DataResponse(data={
        "status": "recorded",
        "decision": body.decision,
        "breach_name": body.breach_name,
        "score": _serialize_risk_summary(score_row, vendor_status=vendor.status or "active"),
    })


@router.post("/{vendor_id}/risk/gst-review", response_model=DataResponse)
async def review_gst_identity(
    vendor_id: str,
    body: GstReviewRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_role("compliance", "admin")),
):
    """Reviewer decision on GST name mismatch/close match equivalence."""
    vendor = await db.get(Vendor, vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="vendor not found")

    _check_reviewer_separation(vendor, user)

    if body.decision not in ("confirmed", "mismatch"):
        raise HTTPException(status_code=400, detail="decision must be 'confirmed' or 'mismatch'")
    if not body.notes or not body.notes.strip():
        raise HTTPException(status_code=400, detail="Reviewer notes are required")

    if body.decision == "confirmed":
        vendor.gstin_verification_status = "confirmed"
    else:
        vendor.gstin_verification_status = "unverified"

    await db.commit()

    # Re-scoring appends fresh observations to append-only table

    score_row = await risk_service.score_vendor(
        db, request.app.state.kafka_producer, vendor.id, trigger_type="gst_review"
    )
    return DataResponse(data={
        "status": "recorded",
        "decision": body.decision,
        "gstin_verification_status": vendor.gstin_verification_status,
        "score": _serialize_risk_summary(score_row, vendor_status=vendor.status or "active"),
    })


@router.post("/{vendor_id}/risk/cert-waiver", response_model=DataResponse)
async def grant_certification_waiver(
    vendor_id: str,
    body: CertWaiverRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_role("admin")),
):
    """Grants a time-bound waiver (max 12 months) for missing security certifications."""
    vendor = await db.get(Vendor, vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="vendor not found")

    _check_reviewer_separation(vendor, user)

    if not body.rationale or not body.rationale.strip():
        raise HTTPException(status_code=400, detail="Waiver rationale is required")

    now = datetime.now(timezone.utc)
    valid_until = now + timedelta(days=30 * body.valid_months)
    approved_by = getattr(user, "email", None) or getattr(user, "user_id", "admin")

    waiver = VendorWaiver(
        id=str(uuid.uuid4()),
        vendor_id=vendor.id,
        waiver_type="certification",
        certification_name=body.certification_name or "SOC2 / ISO 27001",
        rationale=body.rationale.strip(),
        approved_by=approved_by,
        approved_at=now,
        valid_until=valid_until,
        active=True,
    )
    db.add(waiver)
    await db.commit()

    # Re-scoring appends fresh observations to append-only table

    score_row = await risk_service.score_vendor(
        db, request.app.state.kafka_producer, vendor.id, trigger_type="cert_waiver"
    )
    return DataResponse(data={
        "status": "active",
        "waiver_id": waiver.id,
        "valid_until": waiver.valid_until.isoformat(),
        "score": _serialize_risk_summary(score_row, vendor_status=vendor.status or "active"),
    })


@router.post("/{vendor_id}/risk/reevaluate", response_model=DataResponse)
async def reevaluate_risk(
    vendor_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Forces an immediate fresh collection and re-evaluation of all 14 risk signals."""
    vendor = await db.get(Vendor, vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="vendor not found")

    score_row = await risk_service.score_vendor(
        db, request.app.state.kafka_producer, vendor.id, trigger_type="manual_reevaluate", force_fresh_collect=True
    )
    return DataResponse(data=_serialize_risk_summary(score_row, vendor_status=vendor.status or "active"))
