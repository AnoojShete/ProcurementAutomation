"""Vendor endpoints: list, detail, payment-change verification,
no-GSTIN attestation, and 90-day spend summary.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.database import get_db
from app.models import Vendor, VendorPaymentChangeRequest
from app.schemas import DataResponse, VerifyPaymentChangeRequest
from app.services.vendor_payment_service import verify_payment_change, SameSubmitterError
from app.services.vendor_tier_service import (
    get_vendor_spend_90d, check_and_upgrade_tier, confirm_no_gstin,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def _serialize_vendor(v: Vendor) -> dict:
    return {
        "id": v.id,
        "name": v.name,
        "normalized_name": v.normalized_name,
        "status": v.status,
        "vendor_tier": v.vendor_tier,
        "gstin": v.gstin,
        "gstin_verification_status": v.gstin_verification_status,
        "gstin_data_source": v.gstin_data_source,
        "no_gstin_confirmed_by": v.no_gstin_confirmed_by,
        "no_gstin_confirmed_at": v.no_gstin_confirmed_at.isoformat() if v.no_gstin_confirmed_at else None,
        "payment_details_pending_verification": v.payment_details_pending_verification,
        "cumulative_spend_90d": float(v.cumulative_spend_90d) if v.cumulative_spend_90d is not None else 0.0,
        "created_at": v.created_at.isoformat() if v.created_at else None,
        "updated_at": v.updated_at.isoformat() if v.updated_at else None,
    }


def _serialize_change(change: VendorPaymentChangeRequest) -> dict:
    return {
        "id": change.id,
        "vendor_id": change.vendor_id,
        "submitted_by": change.submitted_by,
        "submitted_at": change.submitted_at.isoformat() if change.submitted_at else None,
        "source": change.source,
        "status": change.status,
        "verified_by": change.verified_by,
        "verified_at": change.verified_at.isoformat() if change.verified_at else None,
        "verification_channel": change.verification_channel,
    }


# ---------------------------------------------------------------------------
# GET /vendors — list all vendors
# ---------------------------------------------------------------------------

@router.get("/", response_model=DataResponse)
async def list_vendors(limit: int = 100, db: AsyncSession = Depends(get_db)):
    """List all vendors with GSTIN status and tier info."""
    result = await db.execute(
        select(Vendor).order_by(Vendor.created_at.desc().nulls_last()).limit(limit)
    )
    vendors = list(result.scalars().all())
    return DataResponse(data=[_serialize_vendor(v) for v in vendors], meta={"count": len(vendors)})


# ---------------------------------------------------------------------------
# GET /vendors/{vendor_id} — vendor detail
# ---------------------------------------------------------------------------

@router.get("/{vendor_id}", response_model=DataResponse)
async def get_vendor(vendor_id: str, db: AsyncSession = Depends(get_db)):
    """Vendor detail including tier, GSTIN verification status, and spend."""
    vendor = await db.get(Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail="vendor not found")
    return DataResponse(data=_serialize_vendor(vendor))


# ---------------------------------------------------------------------------
# GET /vendors/{vendor_id}/spend-summary
# ---------------------------------------------------------------------------

@router.get("/{vendor_id}/spend-summary", response_model=DataResponse)
async def get_spend_summary(vendor_id: str, db: AsyncSession = Depends(get_db)):
    """Rolling 90-day spend for this vendor (structuring/tier-upgrade detection)."""
    vendor = await db.get(Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail="vendor not found")
    spend_90d = await get_vendor_spend_90d(db, vendor_id)
    return DataResponse(data={
        "vendor_id": vendor_id,
        "cumulative_spend_90d_inr": spend_90d,
        "current_tier": vendor.vendor_tier,
        "petty_threshold": 5000,
        "standard_threshold": 50000,
    })


# ---------------------------------------------------------------------------
# POST /vendors/{vendor_id}/confirm-no-gstin
# ---------------------------------------------------------------------------

class ConfirmNoGSTINRequest(BaseModel):
    confirmed_by: str
    reason: Optional[str] = None  # e.g. "vendor below GST registration threshold"


@router.post("/{vendor_id}/confirm-no-gstin", response_model=DataResponse)
async def confirm_no_gstin_endpoint(
    vendor_id: str, body: ConfirmNoGSTINRequest, db: AsyncSession = Depends(get_db),
):
    """Explicit attestation that a vendor is below the GST registration
    threshold. Required when onboarding a vendor without a GSTIN — logs
    who confirmed it so the omission is never treated silently."""
    vendor = await db.get(Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail="vendor not found")
    if vendor.gstin:
        raise HTTPException(status_code=409, detail="vendor already has a GSTIN — attestation not applicable")
    await confirm_no_gstin(db, vendor, confirmed_by=body.confirmed_by)
    await db.commit()
    return DataResponse(data={
        "vendor_id": vendor_id,
        "no_gstin_confirmed_by": vendor.no_gstin_confirmed_by,
        "no_gstin_confirmed_at": vendor.no_gstin_confirmed_at.isoformat() if vendor.no_gstin_confirmed_at else None,
    })


# ---------------------------------------------------------------------------
# GET /vendors/{vendor_id}/payment-changes
# ---------------------------------------------------------------------------

@router.get("/{vendor_id}/payment-changes", response_model=DataResponse)
async def list_payment_changes(vendor_id: str, db: AsyncSession = Depends(get_db)):
    vendor = await db.get(Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail="vendor not found")
    result = await db.execute(
        select(VendorPaymentChangeRequest)
        .where(VendorPaymentChangeRequest.vendor_id == vendor_id)
        .order_by(VendorPaymentChangeRequest.created_at.desc())
    )
    changes = list(result.scalars().all())
    return DataResponse(data=[_serialize_change(c) for c in changes])


# ---------------------------------------------------------------------------
# POST /vendors/{vendor_id}/verify-payment-change
# ---------------------------------------------------------------------------

@router.post("/{vendor_id}/verify-payment-change", response_model=DataResponse)
async def verify_payment_change_endpoint(
    vendor_id: str, body: VerifyPaymentChangeRequest, db: AsyncSession = Depends(get_db),
):
    vendor = await db.get(Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail="vendor not found")

    change = await db.get(VendorPaymentChangeRequest, body.change_request_id)
    if change is None or change.vendor_id != vendor_id:
        raise HTTPException(status_code=404, detail="payment change request not found for this vendor")
    if change.status != "pending":
        raise HTTPException(status_code=409, detail=f"change request already {change.status}")

    try:
        change = await verify_payment_change(
            db, change, vendor, verified_by=body.verified_by, channel=body.channel,
            approve=body.approve, notes=body.notes,
        )
    except SameSubmitterError as e:
        raise HTTPException(status_code=403, detail=str(e))

    await db.commit()
    return DataResponse(data=_serialize_change(change))
