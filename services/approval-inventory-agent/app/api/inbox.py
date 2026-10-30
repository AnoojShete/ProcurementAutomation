from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, String, func
from app.database import get_db
from app.models import PurchaseRequest
from app.schemas import DataResponse, InboxItemResponse
from app.services.approval_authority import SELECTABLE_LEVEL, load_delegations
from shared.auth import CurrentUser, get_current_user

router = APIRouter()


def _license_id(req: PurchaseRequest):
    for item in req.items or []:
        if isinstance(item, dict) and item.get("license_id"):
            return str(item["license_id"])
    return None

@router.get("/{approver_id}", response_model=DataResponse)
async def get_inbox(approver_id: str, db: AsyncSession = Depends(get_db),
                    user: CurrentUser = Depends(get_current_user)):
    # Uses PostgreSQL JSON path query to check if current approver matches approver_id
    stmt = (
        select(PurchaseRequest)
        .where(PurchaseRequest.status == "pending_approval")
        # Approximate: Since JSON query depends on dialect, we fetch and filter in python
        # or use a dialect-specific operator. Here we use an approximation or fetch all pending.
    )
    result = await db.execute(stmt)
    requests = result.scalars().all()
    
    # A request with a picked approver waits only in their inbox (and their
    # delegates'); admins still see everything.
    me = (user.email or "").lower()
    now = datetime.now(timezone.utc)
    acting_for = {me} | {
        d.delegator_email.lower() for d in await load_delegations(db, SELECTABLE_LEVEL)
        if d.delegate_email.lower() == me and d.valid_from <= now <= d.valid_until
    }

    inbox_items = []
    for req in requests:
        chain = req.approval_chain or []
        idx = req.current_approver_index
        picked = (req.selected_approver or "").lower()
        if picked and approver_id == SELECTABLE_LEVEL and user.role != "admin" and picked not in acting_for:
            continue
        if idx < len(chain) and chain[idx] == approver_id:
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
                # Reclaim/license requests point at the license they concern, so
                # the inbox can open the license page (where the decision is).
                "license_id": _license_id(req),
                "selected_approver": req.selected_approver,
            })
            
    # Sort by sla_deadline ascending (most urgent first)
    inbox_items.sort(key=lambda x: x["sla_deadline"] or "9999")
    
    return DataResponse(
        data=[InboxItemResponse(**item) for item in inbox_items]
    )
