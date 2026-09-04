from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas import DataResponse, NotificationLogEntry
from app.services import log_service
from shared.auth import require_role

router = APIRouter()


@router.get(
    "/log",
    response_model=DataResponse,
    dependencies=[Depends(require_role("approver", "finance", "admin"))],
)
async def get_notification_log(
    recipient: Optional[str] = None,
    event_type: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
):
    """Searchable audit trail of every notification sent (or queued/failed)."""
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
