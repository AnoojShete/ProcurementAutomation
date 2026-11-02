"""Admin endpoints for OWASP API Security detection, audit events, and IP unblocking."""
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import SecurityEvent
from shared.auth.middleware import require_role, CurrentUser

router = APIRouter(
    prefix="/admin/security",
    dependencies=[Depends(require_role("admin"))],
    tags=["Security Administration"],
)


class SecurityEventResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    timestamp: str
    event_type: str
    user_id: Optional[str] = None
    ip_hash: Optional[str] = None
    route: Optional[str] = None
    detail: dict


class UnblockIPRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ip: str


@router.get("/events")
async def list_security_events(
    event_type: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve recent security detection events with filtering."""
    stmt = select(SecurityEvent).order_by(desc(SecurityEvent.timestamp)).limit(limit)
    if event_type:
        stmt = stmt.where(SecurityEvent.event_type == event_type)
    if user_id:
        stmt = stmt.where(SecurityEvent.user_id == user_id)

    res = await db.execute(stmt)
    events = res.scalars().all()
    return {
        "data": [
            {
                "id": str(e.id),
                "timestamp": e.timestamp.isoformat() if e.timestamp else None,
                "event_type": e.event_type,
                "user_id": e.user_id,
                "ip_hash": e.ip_hash,
                "route": e.route,
                "detail": e.detail,
            }
            for e in events
        ]
    }


@router.post("/unblock-ip")
async def unblock_ip(
    payload: UnblockIPRequest,
    request: Request,
    current_user: CurrentUser = Depends(require_role("admin")),
):
    """Admin unblock for a temporarily blocked IP address."""
    redis = getattr(request.app.state, "redis", None)
    if not redis:
        return {"data": {"message": f"Redis unblock skipped (no active client) for {payload.ip}"}}

    key = f"security:ip_block:{payload.ip}"
    violations_key = f"security:violations:{payload.ip}"
    await redis.delete(key)
    await redis.delete(violations_key)
    return {"data": {"message": f"IP address {payload.ip} unblocked successfully."}}
