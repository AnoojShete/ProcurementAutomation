import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Vendor, RiskScoreOutcome
from app.schemas import DataResponse, LogOutcomeRequest, OffboardVendorRequest
from app.services import risk_service, offboard_service, drift_service

router = APIRouter()


def _serialize_risk(row) -> dict:
    return {
        "vendor_id": row.vendor_id,
        "risk_band": row.band,
        "risk_score": float(row.score) if row.score is not None else None,
        "top_factors": row.details or [],
        "model_version": row.model_version,
        "scored_at": row.scored_at.isoformat() if row.scored_at else None,
    }


@router.get("/{vendor_id}/risk", response_model=DataResponse)
async def get_vendor_risk(vendor_id: str, db: AsyncSession = Depends(get_db)):
    vendor = await db.get(Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail="vendor not found")
    row = await risk_service.latest_risk_score(db, vendor_id)
    if row is None:
        raise HTTPException(status_code=404, detail="vendor has not been risk-scored yet")
    return DataResponse(data=_serialize_risk(row))


@router.post("/{vendor_id}/risk/recompute", response_model=DataResponse)
async def recompute_vendor_risk(vendor_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    vendor = await db.get(Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail="vendor not found")
    row = await risk_service.score_vendor(db, request.app.state.kafka_producer, vendor_id)
    return DataResponse(data=_serialize_risk(row))


@router.post("/{vendor_id}/log-outcome", response_model=DataResponse)
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


@router.post("/{vendor_id}/offboard", response_model=DataResponse)
async def offboard_vendor(vendor_id: str, data: OffboardVendorRequest, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        result = await offboard_service.offboard_vendor(
            db, request.app.state.kafka_producer, vendor_id, data.offboarded_by, data.reason
        )
    except offboard_service.VendorNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return DataResponse(data=result)
