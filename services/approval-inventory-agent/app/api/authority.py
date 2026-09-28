"""Approval authority admin + per-request check. See
app/services/approval_authority.py for the rules."""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services import approval_authority as authority
from app.services.approval_service import ApprovalService
from shared.auth import CurrentUser, get_current_user, require_role

router = APIRouter()


def _audit(db, action: str, entity_id: str, user: CurrentUser, details: dict) -> None:
    # Who can approve what is itself a control: every change is recorded.
    import uuid
    from datetime import datetime, timezone
    from app.models import AuditLog
    db.add(AuditLog(
        id=str(uuid.uuid4()), entity_type="approval_authority", entity_id=entity_id, action=action,
        performed_by=user.email, details=details, created_at=datetime.now(timezone.utc),
    ))


class AssignmentBody(BaseModel):
    level: str = Field(min_length=1, max_length=50)
    user_email: str = Field(min_length=3, max_length=255)
    max_amount: Optional[float] = Field(default=None, ge=0)


class DelegationBody(BaseModel):
    level: str = Field(min_length=1, max_length=50)
    delegate_email: str = Field(min_length=3, max_length=255)
    valid_until: datetime
    reason: str = Field(min_length=3, max_length=500)
    # Admins may record a delegation on someone's behalf; everyone else
    # can only delegate their own authority.
    delegator_email: Optional[str] = None


@router.get("/")
async def get_authority(db: AsyncSession = Depends(get_db), _user: CurrentUser = Depends(get_current_user)):
    return {"data": await authority.list_authority(db)}


@router.get("/check/{request_id}", dependencies=[Depends(require_role("approver", "finance", "admin"))])
async def check(request_id: str, decision: str = "approved", db: AsyncSession = Depends(get_db),
                user: CurrentUser = Depends(get_current_user)):
    """Whether the caller may decide this request right now, and why not."""
    req = await ApprovalService(db, None, None).get_request_with_history(request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="request not found")
    if req.status != "pending_approval":
        return {"data": {"allowed": False, "code": "NOT_PENDING", "reason": f"Request is {req.status.replace('_', ' ')}."}}
    d = await authority.check_request_authority(db, req, user.email, "rejected" if decision == "rejected" else "approved")
    return {"data": {"allowed": d.allowed, "code": d.code, "reason": d.reason, "level": d.level,
                     "via_delegation": d.via_delegation, "limit": d.limit}}


@router.post("/assignments", dependencies=[Depends(require_role("admin"))])
async def add_assignment(body: AssignmentBody, db: AsyncSession = Depends(get_db),
                         user: CurrentUser = Depends(get_current_user)):
    row_id = await authority.upsert_assignment(db, body.level, body.user_email, body.max_amount, user.email)
    _audit(db, "assignment_added", row_id, user, body.model_dump())
    await db.commit()
    return {"data": {"id": row_id}}


@router.delete("/assignments/{assignment_id}", dependencies=[Depends(require_role("admin"))])
async def remove_assignment(assignment_id: str, db: AsyncSession = Depends(get_db),
                            user: CurrentUser = Depends(get_current_user)):
    if not await authority.deactivate_assignment(db, assignment_id):
        raise HTTPException(status_code=404, detail="assignment not found")
    _audit(db, "assignment_removed", assignment_id, user, {})
    await db.commit()
    return {"data": {"id": assignment_id, "active": False}}


@router.post("/delegations", dependencies=[Depends(require_role("approver", "finance", "admin"))])
async def add_delegation(body: DelegationBody, db: AsyncSession = Depends(get_db),
                         user: CurrentUser = Depends(get_current_user)):
    delegator = body.delegator_email if (body.delegator_email and user.role == "admin") else user.email
    try:
        row_id = await authority.create_delegation(
            db, body.level, delegator, body.delegate_email, body.valid_until, body.reason, user.email,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    _audit(db, "delegation_added", row_id, user, {**body.model_dump(mode="json"), "delegator_email": delegator})
    await db.commit()
    return {"data": {"id": row_id}}


@router.delete("/delegations/{delegation_id}", dependencies=[Depends(require_role("approver", "finance", "admin"))])
async def remove_delegation(delegation_id: str, db: AsyncSession = Depends(get_db),
                            user: CurrentUser = Depends(get_current_user)):
    if not await authority.revoke_delegation(db, delegation_id):
        raise HTTPException(status_code=404, detail="delegation not found or already revoked")
    _audit(db, "delegation_revoked", delegation_id, user, {})
    await db.commit()
    return {"data": {"id": delegation_id, "revoked": True}}
