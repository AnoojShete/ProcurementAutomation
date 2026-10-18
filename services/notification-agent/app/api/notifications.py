from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas import DataResponse, FeedEntry, NotificationLogEntry
from app.services import feed, log_service
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


# ---------------------------------------------------------------- the feed
# Your own notifications with read state (app/services/feed.py). The bell
# shows /unread-count; reading happens on the Notifications page.

@router.get("/feed", response_model=DataResponse)
async def get_feed(
    scope: str = Query("important", pattern="^(important|all)$"),
    unread_only: bool = False,
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    rows = await feed.list_feed(db, user, important_only=scope == "important", unread_only=unread_only, limit=limit)
    data = [FeedEntry.model_validate({**NotificationLogEntry.model_validate(n).model_dump(), "read": read})
            for n, read in rows]
    return DataResponse(data=data, meta={"count": len(data), "unread": await feed.unread_count(db, user)})


@router.get("/unread-count", response_model=DataResponse)
async def get_unread_count(db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    return DataResponse(data={"unread": await feed.unread_count(db, user)})


@router.post("/read-all", response_model=DataResponse)
async def read_all(db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    marked = await feed.mark_read(db, user)
    return DataResponse(data={"marked": marked, "unread": await feed.unread_count(db, user)})


@router.post("/{notification_id}/read", response_model=DataResponse)
async def read_one(notification_id: UUID, db: AsyncSession = Depends(get_db),
                   user: CurrentUser = Depends(get_current_user)):
    if not await feed.in_feed(db, user, str(notification_id)):
        raise HTTPException(status_code=404, detail="notification not found")
    marked = await feed.mark_read(db, user, [str(notification_id)])
    return DataResponse(data={"marked": marked, "unread": await feed.unread_count(db, user)})
