"""Writes to notification_log — the audit trail behind GET /notifications/log."""
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import NotificationLog

logger = logging.getLogger(__name__)


async def record(
    db: AsyncSession,
    *,
    recipient: str,
    event_type: str,
    template_name: Optional[str],
    subject: Optional[str],
    body: Optional[str],
    priority: Optional[str],
    related_entity_id: Optional[str],
    status: str,
    error: Optional[str] = None,
    channel: str = "email",
) -> NotificationLog:
    entry = NotificationLog(
        id=str(uuid.uuid4()),
        recipient=recipient,
        channel=channel,
        event_type=event_type,
        template_name=template_name,
        subject=subject,
        body=body,
        priority=priority,
        related_entity_id=str(related_entity_id) if related_entity_id is not None else None,
        status=status,
        error=error,
        sent_at=datetime.now(timezone.utc) if status == "sent" else None,
        created_at=datetime.now(timezone.utc),
    )
    db.add(entry)
    await db.commit()
    return entry


async def search(
    db: AsyncSession,
    *,
    recipient: Optional[str] = None,
    event_type: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = 100,
):
    stmt = select(NotificationLog)
    if recipient:
        stmt = stmt.where(NotificationLog.recipient == recipient)
    if event_type:
        stmt = stmt.where(NotificationLog.event_type == event_type)
    if date_from:
        stmt = stmt.where(NotificationLog.created_at >= date_from)
    if date_to:
        stmt = stmt.where(NotificationLog.created_at <= date_to)
    stmt = stmt.order_by(NotificationLog.created_at.desc()).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())
