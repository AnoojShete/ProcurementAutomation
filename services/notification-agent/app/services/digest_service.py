"""Digest queue: non-urgent events are queued here instead of sent
immediately; flush_due_digests() batches each recipient's queued rows into
one email. Run periodically as a background asyncio task from the FastAPI
lifespan (see app/main.py) — "a minimal correct implementation is fine"
per the brief, so this is deliberately a plain loop, not APScheduler.
"""
import uuid
import logging
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import NotificationDigestQueue
from app.services import templating, email_service, log_service

logger = logging.getLogger(__name__)


async def enqueue(
    db: AsyncSession,
    *,
    recipient: str,
    event_type: str,
    template_name: str,
    template_context: dict,
    related_entity_id: str | None,
) -> NotificationDigestQueue:
    row = NotificationDigestQueue(
        id=str(uuid.uuid4()),
        recipient=recipient,
        event_type=event_type,
        template_name=template_name,
        template_context=template_context,
        related_entity_id=str(related_entity_id) if related_entity_id is not None else None,
        flushed=False,
        created_at=datetime.now(timezone.utc),
    )
    db.add(row)
    await db.commit()

    await log_service.record(
        db,
        recipient=recipient,
        event_type=event_type,
        template_name=template_name,
        subject=None,
        body=None,
        priority="digest",
        related_entity_id=related_entity_id,
        status="queued_digest",
    )
    return row


async def flush_due_digests(db: AsyncSession) -> int:
    """Group all unflushed rows by recipient and send one batched summary
    email per recipient. Returns the number of emails sent."""
    stmt = select(NotificationDigestQueue).where(NotificationDigestQueue.flushed.is_(False))
    result = await db.execute(stmt)
    rows = list(result.scalars().all())
    if not rows:
        return 0

    by_recipient = defaultdict(list)
    for row in rows:
        by_recipient[row.recipient].append(row)

    sent = 0
    for recipient, items in by_recipient.items():
        entries = [
            {
                "event_type": item.event_type,
                "template_name": item.template_name,
                "context": item.template_context or {},
            }
            for item in items
        ]
        try:
            subject, body = templating.render_template(
                "digest_summary", {"recipient": recipient, "entries": entries, "count": len(entries)}
            )
            await email_service.send_email(recipient, subject, body)
            status, error = "sent", None
        except Exception as e:
            logger.error(f"Failed flushing digest for {recipient}: {e}", exc_info=True)
            subject, body, status, error = None, None, "failed", str(e)

        await log_service.record(
            db,
            recipient=recipient,
            event_type="digest.flush",
            template_name="digest_summary",
            subject=subject,
            body=body,
            priority="digest",
            related_entity_id=None,
            status=status,
            error=error,
        )

        if status == "sent":
            now = datetime.now(timezone.utc)
            for item in items:
                item.flushed = True
                item.flushed_at = now
            await db.commit()
            sent += 1

    return sent
