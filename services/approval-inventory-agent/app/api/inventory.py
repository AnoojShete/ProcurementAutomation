"""
Inventory API endpoints for the Approval & Inventory Intelligence Agent.

Provides hardware inventory and license inventory views with
search and filtering capabilities.  License entries now include
anomaly_score and top SHAP factors from the usage anomaly model.

Endpoints
─────────
  GET /inventory                     — hardware + license list (with anomaly_score per license)
  GET /licenses/{license_id}/usage-anomaly — ML anomaly detail: score + top_factors
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas import (
    DataResponse,
    InventoryItemResponse,
    LicenseResponse,
    UsageAnomalyResponse,
    AnomalyFactor,
)
from app.services.inventory_service import get_all_inventory, get_license_inventory
from app.services.usage_service import UsageService

router = APIRouter()


@router.get("/", response_model=DataResponse)
async def list_inventory(
    category: Optional[str] = None,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """List all hardware inventory and software license inventory.

    Query Parameters:
        category: Filter hardware by category (e.g., 'laptop', 'monitor')
        search: Text search across hardware name and SKU

    Returns:
        DataResponse with 'hardware' (list of InventoryItemResponse)
        and 'licenses' (list of LicenseResponse, each including anomaly_score
        and top_factors from the IsolationForest/SHAP model).
    """
    # Hardware inventory from the inventory table
    hw_inv = await get_all_inventory(db, category, search)

    # License inventory with usage aggregations from licenses + license_usage tables.
    # get_license_inventory returns the base utilisation fields; we enrich each entry
    # with the ML anomaly score in a second pass.
    lic_inv = await get_license_inventory(db)

    enriched_licenses = []
    for lic_dict in lic_inv:
        # Run the anomaly scorer for this license and enrich with all fields
        usage_data = await UsageService.compute_utilisation(db, lic_dict["id"])
        if usage_data:
            lic_dict.update(usage_data)
        enriched_licenses.append(LicenseResponse(**lic_dict))

    return DataResponse(
        data={
            "hardware": [
                InventoryItemResponse.model_validate(item) for item in hw_inv
            ],
            "licenses": enriched_licenses,
        },
        meta={
            "hardware_count": len(hw_inv),
            "license_count": len(enriched_licenses),
        }
    )


@router.get("/licenses/anomaly-summary", response_model=DataResponse)
async def get_anomaly_summary(db: AsyncSession = Depends(get_db)):
    """Summary counts of licenses by anomaly status and potential annual savings."""
    summary = await UsageService.get_anomaly_summary(db)
    return DataResponse(data=summary)


@router.get("/licenses/{license_id}/usage-history", response_model=DataResponse)
async def get_license_usage_history(
    license_id: str,
    days: int = 90,
    db: AsyncSession = Depends(get_db),
):
    """Raw daily active seat counts for the last 90 days for a specific license."""
    history = await UsageService.get_usage_history(db, license_id, days=days)
    if history is None:
        raise HTTPException(status_code=404, detail=f"License {license_id} not found")
    return DataResponse(data=history)


@router.get("/licenses/{license_id}/reclaim-history", response_model=DataResponse)
async def get_license_reclaim_history(
    license_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Reclaim events timeline for a specific license."""
    history = await UsageService.get_reclaim_history(db, license_id)
    return DataResponse(data=history)


@router.post("/licenses/{license_id}/mark-reviewed", response_model=DataResponse)
async def mark_license_reviewed(
    license_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Mark a license as reviewed, logging to reclaim history and setting 30-day cooldown."""
    result = await UsageService.mark_reviewed(db, license_id, reviewer="admin@example.com")
    if result is None:
        raise HTTPException(status_code=404, detail=f"License {license_id} not found")
    return DataResponse(data=result)


@router.get("/licenses/{license_id}/usage-anomaly", response_model=DataResponse)
async def get_license_usage_anomaly(
    license_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get the ML anomaly score and SHAP top factors for a specific license."""
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

