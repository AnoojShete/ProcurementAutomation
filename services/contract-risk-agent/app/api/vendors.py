"""Vendor Risk API endpoints (Prompt 9B section 11.1).
Exposes deterministic risk scores, explanation payloads, remediation plans,
replay verification, audit bundles, disputes, and ruleset governance.
"""
import copy
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
)
from app.schemas import DataResponse, LogOutcomeRequest, OffboardVendorRequest
from app.services import clearance, offboard_service, risk_service
from app.services.scorecard.engine import evaluate_risk
from app.services.scorecard.monitoring import generate_monitoring_report
from app.services.scorecard.remediation import build_remediation_plan, simulate_what_if
from app.services.scorecard.traceability import compile_audit_bundle, replay_assessment
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
        "effective_tier": row.effective_tier or "standard",
        "top_contributors": row.details or [],
        "top_factors": row.details or [],
        "ruleset_version": row.ruleset_version or 1,
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
            "created_at": v.created_at.isoformat() if v.created_at else None,
        })
    return DataResponse(data=rows, meta={"count": len(rows)})


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


@router.get("/{vendor_id}/risk/explanation", response_model=DataResponse)
async def get_latest_risk_explanation(vendor_id: str, db: AsyncSession = Depends(get_db)):
    """Full explanation payload for the latest score (Section 7.1)."""
    vendor = await db.get(Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail="vendor not found")
    row = await risk_service.latest_risk_score(db, vendor_id)
    if row is None:
        raise HTTPException(status_code=404, detail="vendor has not been risk-scored yet")
    return DataResponse(data=row.explanation or {})


@router.get("/{vendor_id}/risk/{score_id}/explanation", response_model=DataResponse)
async def get_risk_score_explanation(vendor_id: str, score_id: str, db: AsyncSession = Depends(get_db)):
    """Full explanation payload for a specific historical score (Section 7.1)."""
    score = await db.get(RiskScore, score_id)
    if score is None or score.vendor_id != vendor_id:
        raise HTTPException(status_code=404, detail="risk score not found")
    return DataResponse(data=score.explanation or {})


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
    audience: str = Query("internal", pattern="^(internal|vendor)$"),
    db: AsyncSession = Depends(get_db),
):
    """Deterministic remediation plan. Audience=vendor returns only vendor-safe actions."""
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
        observations=score.snapshot or {},
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

    base_snapshot = score.snapshot if score else {}
    now = datetime.now(timezone.utc)
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
    score_id: str
    rule_result_id: Optional[str] = None
    reason: str = Field(min_length=10, max_length=2000)
    evidence_id: Optional[str] = None


class DisputeReviewRequest(BaseModel):
    decision: str = Field(pattern="^(upheld|rejected)$")
    resolution_note: str = Field(min_length=10, max_length=2000)
    corrected_fields: Optional[Dict[str, Any]] = None


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

    dispute = VendorAssessmentDispute(
        id=str(uuid.uuid4()),
        score_id=body.score_id,
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
    website: Optional[str] = None
    swift_bic: Optional[str] = None
    bank_name: Optional[str] = None


@router.patch("/{vendor_id}", response_model=DataResponse,
              dependencies=[Depends(require_role("finance", "admin"))])
async def update_vendor_fields(vendor_id: str, body: VendorUpdateFields, db: AsyncSession = Depends(get_db)):
    """Updates editable vendor attributes (inherent_tier, website, swift_bic, bank_name)."""
    vendor = await db.get(Vendor, vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="vendor not found")
    if body.inherent_tier is not None:
        val = body.inherent_tier.lower().strip()
        if val not in ("low", "moderate", "high", "critical"):
            raise HTTPException(status_code=400, detail="inherent_tier must be low, moderate, high, or critical")
        vendor.inherent_tier = val
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
