import uuid
from datetime import datetime, timezone

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Vendor, RiskScoreOutcome
from app.schemas import DataResponse, LogOutcomeRequest, OffboardVendorRequest
from app.services import risk_service, offboard_service, drift_service
from shared.auth import CurrentUser, require_role

router = APIRouter()


def _serialize_risk(row) -> dict:
    return {
        "vendor_id": row.vendor_id,
        "risk_band": row.band,
        "risk_score": float(row.score) if row.score is not None else None,
        "top_factors": row.details or [],
        "model_version": row.model_version,
        "scored_at": row.scored_at.isoformat() if row.scored_at else None,
        # FR-04: how many of the model's signals were on file (None for
        # scores from before this was recorded), and the hard-override checks.
        "signals_used": getattr(row, "signals_used", None),
        "signals_total": getattr(row, "signals_total", None),
        "overrides": getattr(row, "overrides", None) or [],
    }


@router.get("/", response_model=DataResponse)
async def list_vendors(limit: int = Query(100, ge=1, le=1000), db: AsyncSession = Depends(get_db)):
    """All vendors with their latest risk score (if any), most recently
    created first — backs the tracking dashboard."""
    result = await db.execute(select(Vendor).order_by(Vendor.created_at.desc().nulls_last()).limit(limit))
    vendors = list(result.scalars().all())
    rows = []
    for v in vendors:
        latest = await risk_service.latest_risk_score(db, v.id)
        rows.append({
            "id": v.id,
            "name": v.name,
            "status": v.status,
            "portal_access_revoked": v.portal_access_revoked,
            "risk_band": latest.band if latest else None,
            "risk_score": float(latest.score) if latest and latest.score is not None else None,
            "created_at": v.created_at.isoformat() if v.created_at else None,
        })
    return DataResponse(data=rows, meta={"count": len(rows)})


@router.get("/{vendor_id}/scorecard", response_model=DataResponse)
async def get_vendor_scorecard(vendor_id: str, db: AsyncSession = Depends(get_db)):
    """Phase 3c: on-time deliveries, invoice accuracy, RFQ response rate,
    SLA breaches and risk band, recomputed now (and stored for RFQ scoring)."""
    from app.services import scorecard
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
async def get_vendor_risk(vendor_id: str, db: AsyncSession = Depends(get_db)):
    vendor = await db.get(Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail="vendor not found")
    row = await risk_service.latest_risk_score(db, vendor_id)
    if row is None:
        raise HTTPException(status_code=404, detail="vendor has not been risk-scored yet")
    return DataResponse(data=_serialize_risk(row))


@router.post(
    "/{vendor_id}/risk/recompute", response_model=DataResponse,
    dependencies=[Depends(require_role("finance", "admin"))],
)
async def recompute_vendor_risk(vendor_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    vendor = await db.get(Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail="vendor not found")
    row = await risk_service.score_vendor(db, request.app.state.kafka_producer, vendor_id)
    return DataResponse(data=_serialize_risk(row))


class ComplianceSignalsBody(BaseModel):
    """Finance's compliance record (BR-7). Omitted fields stay as they are."""
    security_cert_flag: Optional[bool] = None
    geo_risk_flag: Optional[bool] = None
    breach_disclosure_count: Optional[int] = Field(None, ge=0, le=1000)
    financial_stability_score: Optional[float] = Field(None, ge=0, le=1)


async def _signals(db, vendor_id: str) -> dict:
    from app.models import VendorRiskFeatures
    from app.services.risk_signals import COMPLIANCE_FIELDS, platform_signals
    row = await db.get(VendorRiskFeatures, vendor_id)
    compliance = {f: (getattr(row, f) if row else None) for f in COMPLIANCE_FIELDS}
    if compliance["financial_stability_score"] is not None:
        compliance["financial_stability_score"] = float(compliance["financial_stability_score"])
    return {"platform": await platform_signals(db, vendor_id), "compliance": compliance,
            "updated_at": row.updated_at.isoformat() if row and row.updated_at else None}


@router.get("/sanctions-list", response_model=DataResponse, dependencies=[Depends(require_role("finance", "admin"))])
async def sanctions_list_status():
    """Which sanctions list is loaded (FR-14); available=false until
    ./scripts/download-sanctions.sh has been run once."""
    from app.services import sanctions
    return DataResponse(data=sanctions.list_status())


def _serialize_screening(row) -> Optional[dict]:
    if row is None:
        return None
    return {"id": str(row.id), "status": row.status, "screened_at": row.screened_at.isoformat() if row.screened_at else None,
            "list_version": row.list_version, "screened_name": row.screened_name, "matches": row.matches or [],
            "threshold": float(row.threshold) if row.threshold is not None else None,
            "screened_by": row.screened_by, "justification": row.justification}


@router.get("/{vendor_id}/sanctions", response_model=DataResponse)
async def get_sanctions_screening(vendor_id: str, db: AsyncSession = Depends(get_db)):
    from app.services import sanctions
    if await db.get(Vendor, vendor_id) is None:
        raise HTTPException(status_code=404, detail="vendor not found")
    return DataResponse(data={"list": sanctions.list_status(),
                              "latest": _serialize_screening(await sanctions.latest_screening(db, vendor_id))})


@router.post("/{vendor_id}/screen-sanctions", response_model=DataResponse)
async def screen_sanctions(vendor_id: str, request: Request, db: AsyncSession = Depends(get_db),
                           user: CurrentUser = Depends(require_role("finance", "admin"))):
    """Screens the vendor now and re-scores it (a match is a hard override)."""
    from app.services import sanctions
    vendor = await db.get(Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail="vendor not found")
    row = await sanctions.screen_vendor(db, vendor, screened_by=user.email)
    if row is None:
        raise HTTPException(status_code=409, detail={"code": "sanctions_list_missing",
                            "message": "No sanctions list downloaded yet — run ./scripts/download-sanctions.sh."})
    await db.commit()
    risk = await risk_service.score_vendor(db, request.app.state.kafka_producer, vendor_id)
    return DataResponse(data={"screening": _serialize_screening(row), "risk": _serialize_risk(risk)})


class ClearSanctionsBody(BaseModel):
    justification: str = Field(min_length=20, max_length=2000)


@router.post("/{vendor_id}/clear-sanctions-flag", response_model=DataResponse)
async def clear_sanctions_flag(vendor_id: str, body: ClearSanctionsBody, request: Request,
                               db: AsyncSession = Depends(get_db),
                               user: CurrentUser = Depends(require_role("finance", "admin"))):
    """Finance confirms a potential match is a different company; the reason
    is kept and audit-logged, and the vendor is re-scored."""
    from app.services import sanctions
    from app.services.audit import write_audit_log
    if await db.get(Vendor, vendor_id) is None:
        raise HTTPException(status_code=404, detail="vendor not found")
    try:
        row = await sanctions.clear_flag(db, vendor_id, user.email, body.justification)
    except ValueError as e:
        raise HTTPException(status_code=409, detail={"code": "no_open_match", "message": str(e)})
    await write_audit_log(db, "vendor", vendor_id, "sanctions_match_cleared",
                          {"cleared_by": user.email, "justification": row.justification, "matches": row.matches})
    await db.commit()
    risk = await risk_service.score_vendor(db, request.app.state.kafka_producer, vendor_id)
    return DataResponse(data={"screening": _serialize_screening(row), "risk": _serialize_risk(risk)})


@router.get("/{vendor_id}/risk-signals", response_model=DataResponse)
async def get_risk_signals(vendor_id: str, db: AsyncSession = Depends(get_db)):
    """What the risk model knows about a vendor: platform history (tenure,
    on-time delivery) and finance's compliance record."""
    if await db.get(Vendor, vendor_id) is None:
        raise HTTPException(status_code=404, detail="vendor not found")
    return DataResponse(data=await _signals(db, vendor_id))


@router.patch("/{vendor_id}/risk-signals", response_model=DataResponse)
async def update_risk_signals(vendor_id: str, body: ComplianceSignalsBody, request: Request,
                              db: AsyncSession = Depends(get_db),
                              user: CurrentUser = Depends(require_role("finance", "admin"))):
    """Records compliance signals (audit-logged) and re-scores the vendor."""
    from app.services.risk_signals import update_compliance_signals
    if await db.get(Vendor, vendor_id) is None:
        raise HTTPException(status_code=404, detail="vendor not found")
    changes = body.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(status_code=422, detail={"code": "nothing_to_update", "message": "No signal given."})
    await update_compliance_signals(db, vendor_id, changes, user.email)
    await db.commit()
    row = await risk_service.score_vendor(db, request.app.state.kafka_producer, vendor_id)
    return DataResponse(data={"risk": _serialize_risk(row), "signals": await _signals(db, vendor_id)})


@router.post(
    "/{vendor_id}/log-outcome", response_model=DataResponse,
    dependencies=[Depends(require_role("finance", "admin"))],
)
async def log_outcome(vendor_id: str, data: LogOutcomeRequest, db: AsyncSession = Depends(get_db)):
    vendor = await db.get(Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail="vendor not found")
    latest = await risk_service.latest_risk_score(db, vendor_id)

    outcome = RiskScoreOutcome(
        id=str(uuid.uuid4()),
        vendor_id=vendor_id,
        risk_score_at_time=float(latest.score) if latest and latest.score is not None else None,
        risk_band_at_time=latest.band if latest else None,
        actual_incident_occurred=data.actual_incident_occurred,
        notes=data.notes,
        logged_by=data.logged_by,
        logged_at=datetime.now(timezone.utc),
    )
    db.add(outcome)
    await db.commit()
    return DataResponse(data={
        "id": outcome.id,
        "vendor_id": vendor_id,
        "actual_incident_occurred": data.actual_incident_occurred,
        "logged_at": outcome.logged_at.isoformat(),
    })


@router.get("/risk-model/drift-check", response_model=DataResponse)
async def risk_model_drift_check(db: AsyncSession = Depends(get_db)):
    """Manual trigger for the weekly drift check (also run on a schedule
    by the DriftMonitoringWorkflow). Monitoring signal only — never
    retrains automatically."""
    result = await drift_service.check_drift(db)
    return DataResponse(data=result)


@router.post(
    "/{vendor_id}/offboard", response_model=DataResponse,
    dependencies=[Depends(require_role("admin"))],
)
async def offboard_vendor(vendor_id: str, data: OffboardVendorRequest, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        result = await offboard_service.offboard_vendor(
            db, request.app.state.kafka_producer, vendor_id, data.offboarded_by, data.reason
        )
    except offboard_service.VendorNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return DataResponse(data=result)
