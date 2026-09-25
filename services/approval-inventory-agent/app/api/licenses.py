"""
Dedicated Licenses API router for Approval & Inventory Intelligence Agent.
Endpoints:
  GET  /licenses/anomaly-summary
  GET  /licenses/{license_id}/usage-history
  GET  /licenses/{license_id}/reclaim-history
  POST /licenses/{license_id}/mark-reviewed
  GET  /licenses/{license_id}/usage-anomaly
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas import (
    DataResponse,
    UsageAnomalyResponse,
    AnomalyFactor,
    LicenseAnomalySummary,
    UsageHistoryEntry,
    ReclaimHistoryEntry,
)
from app.services.usage_service import UsageService
from shared.auth import CurrentUser, require_role

router = APIRouter()


@router.get("/anomaly-summary", response_model=DataResponse)
async def get_anomaly_summary(db: AsyncSession = Depends(get_db)):
    """Summary counts of licenses by anomaly status and potential annual savings."""
    summary = await UsageService.get_anomaly_summary(db)
    return DataResponse(data=summary)


@router.get("/{license_id}/usage-history", response_model=DataResponse)
async def get_usage_history(
    license_id: str,
    days: int = 90,
    db: AsyncSession = Depends(get_db),
):
    """Raw daily active seat counts for the last 90 days for a specific license."""
    history = await UsageService.get_usage_history(db, license_id, days=days)
    if history is None:
        raise HTTPException(status_code=404, detail=f"License {license_id} not found")
    return DataResponse(data=history)


@router.get("/{license_id}/reclaim-history", response_model=DataResponse)
async def get_reclaim_history(
    license_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Reclaim events timeline for a specific license."""
    history = await UsageService.get_reclaim_history(db, license_id)
    return DataResponse(data=history)


@router.post("/{license_id}/mark-reviewed", response_model=DataResponse)
async def mark_license_reviewed(
    license_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_role("approver", "finance", "admin")),
):
    """Mark a license as reviewed, logging to reclaim history and setting 30-day cooldown.

    Limited to the roles that see the Licenses page: the 30-day cooldown
    suppresses automatic reclaim, so requesters must not be able to set it.
    """
    result = await UsageService.mark_reviewed(db, license_id, reviewer=user.email)
    if result is None:
        raise HTTPException(status_code=404, detail=f"License {license_id} not found")
    return DataResponse(data=result)


@router.get("/{license_id}/usage-anomaly", response_model=DataResponse)
async def get_license_usage_anomaly(
    license_id: str,
    db: AsyncSession = Depends(get_db),
):
    """ML anomaly score and top SHAP factors for a specific license."""
    usage_data = await UsageService.compute_utilisation(db, license_id)
    if usage_data is None:
        raise HTTPException(
            status_code=404,
            detail=f"License {license_id} not found or not active",
        )

    anomaly_response = UsageAnomalyResponse(
        license_id=str(usage_data["license_id"]),
        app_name=usage_data["app_name"],
        anomaly_score=usage_data.get("anomaly_score") or 0.0,
        top_factors=[
            AnomalyFactor(**f) for f in usage_data.get("top_factors", [])
        ],
        model_version=usage_data.get("model_version", "not_trained"),
        utilisation_score=usage_data["utilisation_score"],
        active_seats_30d=usage_data["active_seats_30d"],
        total_seats=usage_data["total_seats"],
    )

    return DataResponse(
        data={"usage_anomaly": anomaly_response.model_dump()},
        meta={"license_id": license_id},
    )
