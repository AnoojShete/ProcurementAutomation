"""Vendor endpoints: list, detail, payment-change verification,
no-GSTIN attestation, and 90-day spend summary.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Body, Request, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.database import get_db
from app.models import Document, Vendor, VendorPaymentChangeRequest
from app.schemas import DataResponse, VerifyPaymentChangeRequest
from app.services.vendor_payment_service import verify_payment_change, SameSubmitterError
from app.services.vendor_tier_service import (
    get_vendor_spend_90d, check_and_upgrade_tier, confirm_no_gstin,
)
from shared.auth import CurrentUser, require_role

import logging
logger = logging.getLogger(__name__)

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
        "inherent_tier": getattr(v, "inherent_tier", None),
        "swift_bic": getattr(v, "swift_bic", None),
        "bank_name": getattr(v, "bank_name", None),
        "website": getattr(v, "website", None),
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
        "document_id": change.document_id,
        # Masked: enough for a verifier to read back on a call-back, never
        # the full number in an API response.
        "previous_account_last4": _last4(change.previous_bank_account_number),
        "new_account_last4": _last4(change.new_bank_account_number),
        "new_routing_code": change.new_routing_code,
        "new_beneficiary_name": change.new_beneficiary_name,
    }


def _last4(value: Optional[str]) -> Optional[str]:
    return f"••••{value[-4:]}" if value else None


# ---------------------------------------------------------------------------
# GET /vendors — list all vendors
# ---------------------------------------------------------------------------

@router.get("/", response_model=DataResponse)
async def list_vendors(limit: int = Query(100, ge=1, le=1000), db: AsyncSession = Depends(get_db)):
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
    # Ignored — the attester is the authenticated caller (see endpoint).
    confirmed_by: Optional[str] = None
    reason: Optional[str] = None  # e.g. "vendor below GST registration threshold"


@router.post("/{vendor_id}/confirm-no-gstin", response_model=DataResponse)
async def confirm_no_gstin_endpoint(
    vendor_id: str,
    body: ConfirmNoGSTINRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_role("finance", "admin")),
):
    """Explicit attestation that a vendor is below the GST registration
    threshold. Required when onboarding a vendor without a GSTIN — logs
    who confirmed it so the omission is never treated silently."""
    vendor = await db.get(Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail="vendor not found")
    if vendor.gstin:
        raise HTTPException(status_code=409, detail="vendor already has a GSTIN — attestation not applicable")
    await confirm_no_gstin(db, vendor, confirmed_by=user.email)
    await db.commit()
    return DataResponse(data={
        "vendor_id": vendor_id,
        "no_gstin_confirmed_by": vendor.no_gstin_confirmed_by,
        "no_gstin_confirmed_at": vendor.no_gstin_confirmed_at.isoformat() if vendor.no_gstin_confirmed_at else None,
    })


# ---------------------------------------------------------------------------
# GET /vendors/{vendor_id}/payment-changes
# ---------------------------------------------------------------------------

@router.get("/{vendor_id}/payment-changes", response_model=DataResponse,
            dependencies=[Depends(require_role("finance", "admin"))])
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
    vendor_id: str,
    body: VerifyPaymentChangeRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_role("finance", "admin")),
):
    vendor = await db.get(Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail="vendor not found")

    change = await db.get(VendorPaymentChangeRequest, body.change_request_id)
    if change is None or change.vendor_id != vendor_id:
        raise HTTPException(status_code=404, detail="payment change request not found for this vendor")
    if change.status != "pending":
        raise HTTPException(status_code=409, detail=f"change request already {change.status}")

    # verified_by is derived from the caller's authenticated identity, never
    # from the request body — otherwise dual control is trivially bypassed
    # by self-submitting a verified_by that merely differs textually from
    # submitted_by.
    try:
        change = await verify_payment_change(
            db, change, vendor, verified_by=user.email, channel=body.channel,
            approve=body.approve, notes=body.notes,
        )
    except SameSubmitterError as e:
        raise HTTPException(status_code=403, detail=str(e))

    await db.commit()
    released = 0
    if change.status == "verified" and not vendor.payment_details_pending_verification:
        released = await release_payment_holds(db, vendor_id)
    return DataResponse(data=_serialize_change(change), meta={"payment_holds_released": released})


async def release_payment_holds(db: AsyncSession, vendor_id: str) -> int:
    """Once a vendor's bank details are verified, its held invoices become
    payable: clear the hold on the documents and in the invoice ledger."""
    from sqlalchemy import text as sql_text
    docs = (
        await db.execute(select(Document).where(Document.vendor_id == vendor_id, Document.document_type == "invoice"))
    ).scalars().all()
    released = 0
    for doc in docs:
        extracted = dict(doc.extracted or {})
        if extracted.get("payment_hold"):
            extracted["payment_hold"] = False
            extracted["payment_hold_released_at"] = datetime.now(timezone.utc).isoformat()
            doc.extracted = extracted
            released += 1
    await db.commit()
    import os
    import httpx
    from shared.auth.jwt_tokens import create_access_token
    url = os.environ.get("APPROVAL_INVENTORY_URL", "http://approval-inventory-agent:8002").rstrip("/")
    token = create_access_token("document-vendor-agent", "document-vendor-agent@service.internal", "service")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(f"{url}/invoices/release-holds/{vendor_id}", headers={"Authorization": f"Bearer {token}"})
    except Exception as e:
        logger.warning(f"Could not release ledger payment holds for vendor {vendor_id}: {e}")
    return released


@router.get("/payment-changes/pending", response_model=DataResponse,
            dependencies=[Depends(require_role("finance", "admin"))])
async def list_pending_payment_changes(db: AsyncSession = Depends(get_db)):
    """Verification queue across all vendors (finance works through this)."""
    rows = (
        await db.execute(
            select(VendorPaymentChangeRequest, Vendor.name)
            .join(Vendor, Vendor.id == VendorPaymentChangeRequest.vendor_id)
            .where(VendorPaymentChangeRequest.status == "pending")
            .order_by(VendorPaymentChangeRequest.created_at.desc())
        )
    ).all()
    return DataResponse(data=[{**_serialize_change(c), "vendor_name": name} for c, name in rows])


# ── Onboarding (BR-4) ──────────────────────────────────────────────────────

class VendorOnboardBody(BaseModel):
    name: str
    country: Optional[str] = None
    inherent_tier: Optional[str] = None
    swift_bic: Optional[str] = None
    bank_name: Optional[str] = None
    website: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    address: Optional[str] = None
    category: Optional[str] = None
    gstin: Optional[str] = None
    bank_account_number: Optional[str] = None
    routing_code: Optional[str] = None
    payment_beneficiary_name: Optional[str] = None
    # Warnings the person has seen and accepted: "lookalike", "no_gstin".
    confirm: list[str] = []
    no_gstin_reason: Optional[str] = None


def _profile(body: VendorOnboardBody):
    from app.services.vendor_onboarding import VendorProfile
    return VendorProfile(**body.model_dump(exclude={"confirm", "no_gstin_reason"}))


@router.post("/onboard/validate", response_model=DataResponse,
             dependencies=[Depends(require_role("finance", "admin"))])
async def validate_onboarding(body: VendorOnboardBody, db: AsyncSession = Depends(get_db)):
    """Checks a vendor profile without saving anything (live form feedback)."""
    from app.services.ifsc_service import validate_ifsc
    from app.services.vendor_onboarding import required_confirmations, validate_profile
    check = await validate_profile(db, _profile(body), check_ifsc=validate_ifsc)
    return DataResponse(data={"ok": check.ok, "errors": check.errors, "warnings": check.warnings,
                              "needs_confirmation": sorted(required_confirmations(check))})


@router.post("/onboard", response_model=DataResponse, status_code=201)
async def onboard(body: VendorOnboardBody, request: Request, db: AsyncSession = Depends(get_db),
                  user: CurrentUser = Depends(require_role("finance", "admin"))):
    """Creates a vendor after the profile checks pass. Bank details go to
    the two-person verification queue, never straight onto the vendor."""
    from app.services.ifsc_service import validate_ifsc
    from app.services.vendor_onboarding import onboard_vendor
    vendor, check, missing = await onboard_vendor(
        db, getattr(request.app.state, "kafka_producer", None), _profile(body), user.email,
        set(body.confirm), body.no_gstin_reason, check_ifsc=validate_ifsc,
    )
    if vendor is None:
        raise HTTPException(status_code=422, detail={
            "code": "vendor_profile_invalid" if check.errors else "confirmation_required",
            "message": (check.errors[0]["message"] if check.errors
                        else "Confirm the warnings first: " + ", ".join(sorted(missing))),
        })
    return DataResponse(data={"id": str(vendor.id), "name": vendor.name,
                              "payment_details_pending_verification": bool(vendor.payment_details_pending_verification),
                              "warnings": check.warnings})


class VendorPatchRequest(BaseModel):
    inherent_tier: Optional[str] = None
    website: Optional[str] = None
    swift_bic: Optional[str] = None
    bank_name: Optional[str] = None


@router.patch("/{vendor_id}", response_model=DataResponse,
              dependencies=[Depends(require_role("finance", "admin"))])
async def patch_vendor_profile(vendor_id: str, body: VendorPatchRequest, db: AsyncSession = Depends(get_db)):
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
    vendor.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(vendor)
    return DataResponse(data=_serialize_vendor(vendor))
