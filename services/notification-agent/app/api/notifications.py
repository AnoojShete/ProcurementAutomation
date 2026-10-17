from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas import DataResponse, NotificationLogEntry
from app.services import log_service
from shared.auth import CurrentUser, get_current_user

router = APIRouter()

# Staff search the whole log; anyone else sees only notifications addressed
# to them (the recipient filter comes from the JWT, not the query string).
STAFF_ROLES = frozenset({"approver", "finance", "admin"})


@router.get("/log", response_model=DataResponse)
async def get_notification_log(
    recipient: Optional[str] = None,
    event_type: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Searchable audit trail of every notification sent (or queued/failed)."""
    if user.role not in STAFF_ROLES:
        recipient = user.email
    entries = await log_service.search(
        db,
        recipient=recipient,
        event_type=event_type,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )
    return DataResponse(
        data=[NotificationLogEntry.model_validate(e) for e in entries],
        meta={"count": len(entries)},
    )
