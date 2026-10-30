from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.database import get_db
from app.models import PurchaseRequest
from app.schemas import DataResponse, InboxItemResponse
from shared.auth import CurrentUser, get_current_user

router = APIRouter()


def _license_id(req: PurchaseRequest):
    for item in req.items or []:
        if isinstance(item, dict) and item.get("license_id"):
            return str(item["license_id"])
    return None


@router.get("/{approver_id}", response_model=DataResponse)
async def get_inbox(
    approver_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    stmt = (
        select(PurchaseRequest)
        .options(selectinload(PurchaseRequest.approval_history))
        .where(PurchaseRequest.status == "pending_approval")
    )
    result = await db.execute(stmt)
    requests = result.scalars().all()
    
    inbox_items = []
    for req in requests:
        chain = req.approval_chain or []
        idx = req.current_approver_index
        if idx < len(chain) and chain[idx] == approver_id:
            # If current user already approved this request, exclude from their active pending inbox
            if any(
                h.decided_by == user.email and h.decision == "approved"
                for h in (req.approval_history or [])
            ):
                continue

            inbox_items.append({
                "request_id": req.id,
                "request_type": req.request_type,
                "requested_by": req.requested_by,
                "department": req.department,
                "amount": req.amount,
                "currency": req.currency,
                "spend_tier": req.spend_tier,
                "sla_deadline": req.sla_deadline.isoformat() if req.sla_deadline else None,
                "created_at": req.created_at.isoformat() if req.created_at else None,
                "license_id": _license_id(req),
            })
            
    # Sort by sla_deadline ascending (most urgent first)
    inbox_items.sort(key=lambda x: x["sla_deadline"] or "9999")
    
    return DataResponse(
        data=[InboxItemResponse(**item) for item in inbox_items]
    )
