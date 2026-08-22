from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, String, func
from app.database import get_db
from app.models import PurchaseRequest
from app.schemas import DataResponse, InboxItemResponse

router = APIRouter()

@router.get("/{approver_id}", response_model=DataResponse)
async def get_inbox(approver_id: str, db: AsyncSession = Depends(get_db)):
    # Uses PostgreSQL JSON path query to check if current approver matches approver_id
    stmt = (
        select(PurchaseRequest)
        .where(PurchaseRequest.status == "pending_approval")
        # Approximate: Since JSON query depends on dialect, we fetch and filter in python
        # or use a dialect-specific operator. Here we use an approximation or fetch all pending.
    )
    result = await db.execute(stmt)
    requests = result.scalars().all()
    
    inbox_items = []
    for req in requests:
        chain = req.approval_chain or []
        idx = req.current_approver_index
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
                "created_at": req.created_at.isoformat()
            })
            
    # Sort by sla_deadline ascending (most urgent first)
    inbox_items.sort(key=lambda x: x["sla_deadline"] or "9999")
    
    return DataResponse(
        data=[InboxItemResponse(**item) for item in inbox_items]
    )
