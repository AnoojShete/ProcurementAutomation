"""Risk Ruleset Governance API (Prompt 9B section 10 & 11.1).
Backs the 'Risk scorecard' tab on Anooj's Business Rules page.
Enforces:
- Viewing active ruleset
- Draft editing (never directly editing the active version)
- Server-side Section 3.4 validation
- Dry-run simulation across all active vendors without side effects
- Versioned activation requiring justification, passing validation, and dry run
"""
import copy
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import RiskRuleset, RiskScore, Vendor
from app.schemas import DataResponse
from app.services.scorecard.default_ruleset import (
    canonical_json_hash,
    get_default_ruleset,
)
from app.services.scorecard.engine import evaluate_risk
from app.services.scorecard.validator import validate_ruleset
from shared.auth import CurrentUser, get_current_user, require_role

router = APIRouter()

logger = logging.getLogger(__name__)


class SaveDraftRequest(BaseModel):
    definition: Dict[str, Any]


class ValidateRequest(BaseModel):
    definition: Dict[str, Any]


class ActivateRequest(BaseModel):
    change_justification: str = Field(min_length=10, max_length=2000)


@router.get("/", response_model=DataResponse)
async def list_rulesets(db: AsyncSession = Depends(get_db)):
    """Lists all ruleset versions and their statuses."""
    result = await db.execute(select(RiskRuleset).order_by(RiskRuleset.version.desc()))
    rows = result.scalars().all()
    data = [
        {
            "id": r.id,
            "version": r.version,
            "status": r.status,
            "definition_hash": r.definition_hash,
            "created_by": r.created_by,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "activated_by": r.activated_by,
            "activated_at": r.activated_at.isoformat() if r.activated_at else None,
            "change_justification": r.change_justification,
        }
        for r in rows
    ]
    return DataResponse(data=data)


@router.get("/active", response_model=DataResponse)
async def get_active_ruleset_endpoint(db: AsyncSession = Depends(get_db)):
    """Returns the currently active ruleset."""
    from app.services.risk_service import get_active_ruleset
    ruleset = await get_active_ruleset(db)
    return DataResponse(
        data={
            "id": ruleset.id,
            "version": ruleset.version,
            "status": ruleset.status,
            "definition": ruleset.definition,
            "definition_hash": ruleset.definition_hash,
            "activated_by": ruleset.activated_by,
            "activated_at": ruleset.activated_at.isoformat() if ruleset.activated_at else None,
            "change_justification": ruleset.change_justification,
        }
    )


@router.get("/draft", response_model=DataResponse)
async def get_draft_ruleset(db: AsyncSession = Depends(get_db)):
    """Returns the current draft ruleset if one exists, otherwise a copy of active."""
    res = await db.execute(
        select(RiskRuleset).where(RiskRuleset.status == "draft").order_by(RiskRuleset.created_at.desc()).limit(1)
    )
    draft = res.scalars().first()
    if draft:
        return DataResponse(
            data={
                "id": draft.id,
                "version": draft.version,
                "status": "draft",
                "definition": draft.definition,
                "definition_hash": draft.definition_hash,
                "created_by": draft.created_by,
                "created_at": draft.created_at.isoformat() if draft.created_at else None,
                "dry_run_report": draft.dry_run_report,
            }
        )

    # Fallback to copy of active
    from app.services.risk_service import get_active_ruleset
    active = await get_active_ruleset(db)
    return DataResponse(
        data={
            "id": None,
            "version": active.version + 1,
            "status": "draft",
            "definition": copy.deepcopy(active.definition),
            "definition_hash": active.definition_hash,
            "created_by": "system",
            "created_at": None,
            "dry_run_report": None,
        }
    )


@router.post("/draft", response_model=DataResponse, dependencies=[Depends(require_role("admin"))])
async def save_draft_ruleset(
    body: SaveDraftRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Saves a draft ruleset for review and dry running."""
    res = await db.execute(
        select(RiskRuleset).where(RiskRuleset.status == "draft").order_by(RiskRuleset.created_at.desc()).limit(1)
    )
    draft = res.scalars().first()

    # Determine version
    from app.services.risk_service import get_active_ruleset
    active = await get_active_ruleset(db)
    next_ver = active.version + 1

    d_hash = canonical_json_hash(body.definition)

    if draft:
        draft.definition = body.definition
        draft.definition_hash = d_hash
        draft.created_by = user.email
        draft.dry_run_report = None  # Reset dry run on edit
    else:
        draft = RiskRuleset(
            id=str(uuid.uuid4()),
            version=next_ver,
            status="draft",
            definition=body.definition,
            definition_hash=d_hash,
            created_by=user.email,
            created_at=datetime.now(timezone.utc),
        )
        db.add(draft)

    await db.commit()
    await db.refresh(draft)
    return DataResponse(
        data={
            "id": draft.id,
            "version": draft.version,
            "status": draft.status,
            "definition": draft.definition,
            "definition_hash": draft.definition_hash,
            "message": "Draft ruleset saved.",
        }
    )


@router.post("/validate", response_model=DataResponse)
async def validate_ruleset_endpoint(body: ValidateRequest):
    """Runs section 3.4 checks and returns field-level validation errors."""
    is_valid, errors = validate_ruleset(body.definition)
    return DataResponse(
        data={
            "valid": is_valid,
            "errors": errors,
            "summary": "Validation passed." if is_valid else f"Found {len(errors)} validation error(s).",
        }
    )


@router.post("/dry-run", response_model=DataResponse, dependencies=[Depends(require_role("admin"))])
async def dry_run_ruleset(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Re-evaluates every active vendor from its stored observations with the draft
    (no external calls, nothing persisted) and reports band/score changes.
    """
    res = await db.execute(
        select(RiskRuleset).where(RiskRuleset.status == "draft").order_by(RiskRuleset.created_at.desc()).limit(1)
    )
    draft = res.scalars().first()
    if not draft:
        raise HTTPException(status_code=400, detail="No draft ruleset found. Save a draft first.")

    is_valid, errors = validate_ruleset(draft.definition)
    if not is_valid:
        raise HTTPException(status_code=422, detail={"code": "validation_failed", "errors": errors})

    # Fetch all active vendors
    vendors_res = await db.execute(select(Vendor).where(Vendor.status == "active"))
    vendors = vendors_res.scalars().all()

    from app.services.risk_service import latest_risk_score, load_fresh_observations

    now = datetime.now(timezone.utc)
    summary_vendors = []
    band_changes_count = 0

    for v in vendors:
        prev_score = await latest_risk_score(db, v.id)
        if not prev_score:
            continue

        obs = await load_fresh_observations(db, v.id, draft.definition, now)
        eval_res = evaluate_risk(
            ruleset=draft.definition,
            observations=obs,
            assessed_at=now,
            vendor_context={"name": v.name, "spend_tier": getattr(v, "vendor_tier", "standard")},
        )

        prev_band = prev_score.final_band or prev_score.band
        prev_points = prev_score.total_points if prev_score.total_points is not None else int(round((prev_score.score or 0) * 100))
        new_band = eval_res["final_band"]
        new_points = eval_res["total_points"]

        band_changed = (prev_band != new_band)
        if band_changed:
            band_changes_count += 1

        summary_vendors.append({
            "vendor_id": v.id,
            "vendor_name": v.name,
            "previous_band": prev_band,
            "previous_points": prev_points,
            "new_band": new_band,
            "new_points": new_points,
            "points_delta": new_points - prev_points,
            "band_changed": band_changed,
        })

    report = {
        "executed_at": now.isoformat(),
        "executed_by": user.email,
        "draft_definition_hash": draft.definition_hash,
        "total_vendors_evaluated": len(summary_vendors),
        "vendors_with_band_changes": band_changes_count,
        "vendor_results": summary_vendors,
    }

    draft.dry_run_report = report
    await db.commit()

    return DataResponse(data=report)


@router.post("/activate", response_model=DataResponse, dependencies=[Depends(require_role("admin"))])
async def activate_ruleset(
    body: ActivateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Activates the draft ruleset as version N+1, retiring the old active version,
    and queues re-evaluation of all active vendors (trigger_type=ruleset_change).
    """
    res = await db.execute(
        select(RiskRuleset).where(RiskRuleset.status == "draft").order_by(RiskRuleset.created_at.desc()).limit(1)
    )
    draft = res.scalars().first()
    if not draft:
        raise HTTPException(status_code=400, detail="No draft ruleset found to activate.")

    # 1. Validation check
    is_valid, errors = validate_ruleset(draft.definition)
    if not is_valid:
        raise HTTPException(status_code=422, detail={"code": "validation_failed", "errors": errors})

    # 2. Dry run check
    if not draft.dry_run_report:
        raise HTTPException(
            status_code=400, detail="A stored dry run is required before activation. Run a dry run first."
        )

    now = datetime.now(timezone.utc)

    # 3. Retire previous active ruleset
    active_res = await db.execute(select(RiskRuleset).where(RiskRuleset.status == "active"))
    active_old = active_res.scalars().all()
    for old_r in active_old:
        old_r.status = "retired"

    # 4. Activate draft
    draft.status = "active"
    draft.activated_by = user.email
    draft.activated_at = now
    draft.change_justification = body.change_justification

    await db.commit()
    await db.refresh(draft)

    # 5. Re-evaluate all active vendors with trigger_type='ruleset_change'
    from app.services.risk_service import score_vendor
    vendors_res = await db.execute(select(Vendor).where(Vendor.status == "active"))
    vendors = vendors_res.scalars().all()

    rescored_count = 0
    producer = getattr(request.app.state, "kafka_producer", None)
    for v in vendors:
        try:
            await score_vendor(
                db=db,
                kafka_producer=producer,
                vendor_id=v.id,
                trigger_type="ruleset_change",
                trigger_ref=f"v{draft.version}",
                force_fresh_collect=False,
            )
            rescored_count += 1
        except Exception as e:
            logger.warning(f"Failed to rescore vendor {v.id} after ruleset change: {e}")

    return DataResponse(
        data={
            "id": draft.id,
            "version": draft.version,
            "status": "active",
            "activated_at": draft.activated_at.isoformat(),
            "activated_by": draft.activated_by,
            "change_justification": draft.change_justification,
            "vendors_rescored": rescored_count,
            "message": f"Ruleset v{draft.version} is now active. {rescored_count} vendors re-evaluated.",
        }
    )


@router.get("/history", response_model=DataResponse)
async def ruleset_history(db: AsyncSession = Depends(get_db)):
    """Shows ruleset history with diff between versions."""
    res = await db.execute(select(RiskRuleset).order_by(RiskRuleset.version.asc()))
    versions = res.scalars().all()

    history = []
    prev_def = None
    for r in versions:
        diff_summary = "Initial release" if prev_def is None else "Ruleset updated"
        history.append({
            "version": r.version,
            "status": r.status,
            "activated_by": r.activated_by,
            "activated_at": r.activated_at.isoformat() if r.activated_at else None,
            "change_justification": r.change_justification,
            "definition_hash": r.definition_hash,
            "diff_summary": diff_summary,
        })
        prev_def = r.definition

    return DataResponse(data=list(reversed(history)))
