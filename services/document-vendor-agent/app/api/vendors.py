from sqlalchemy import select
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Vendor, VendorPaymentChangeRequest
from app.schemas import DataResponse, VerifyPaymentChangeRequest
from app.services.vendor_payment_service import verify_payment_change, SameSubmitterError
from shared.auth import CurrentUser, require_role

router = APIRouter()


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


@router.post(
    "/{vendor_id}/verify-payment-change",
    response_model=DataResponse,
    dependencies=[Depends(require_role("finance", "admin"))],
)
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

    return DataResponse(data=_serialize_change(change))
