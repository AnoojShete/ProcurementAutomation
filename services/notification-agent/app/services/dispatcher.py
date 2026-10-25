"""The single entry point every Kafka handler in app/kafka/consumer.py
calls: decide urgent-vs-digest, then either render+send+log immediately,
or queue for the next digest flush."""
import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import routing, template_store, email_service, log_service, digest_service
from app.metrics import notification_sent_total

logger = logging.getLogger(__name__)


async def notify(
    db: AsyncSession,
    *,
    event_type: str,
    template_name: str,
    context: dict,
    recipient: str,
    related_entity_id: Optional[str] = None,
    priority_override: Optional[str] = None,
) -> str:
    """Route + deliver one notification. Returns the priority it was sent
    at ("urgent" or "digest")."""
    priority = priority_override or routing.decide_priority(event_type, context)

    if priority == routing.URGENT:
        try:
            email = await template_store.render(db, template_name, context)
            if not email.enabled:
                # Turned off on the Control Panel: logged, not sent.
                await log_service.record(
                    db, recipient=recipient, event_type=event_type, template_name=template_name,
                    subject=None, body=None, priority=priority, related_entity_id=related_entity_id,
                    status="skipped", error="template turned off in the Control Panel",
                )
                return priority
            # Use configured recipient override if set on the template, else routed recipient.
            primary_to = email.recipient if (email.recipient and email.recipient.strip()) else recipient
            # The primary recipient, plus any copies set on the template.
            for to in [primary_to] + [r for r in email.extra_recipients if r != primary_to]:
                await email_service.send_email(to, email.subject, email.body, db=db)
                await log_service.record(
                    db,
                    recipient=to,
                    event_type=event_type,
                    template_name=template_name,
                    subject=email.subject,
                    body=email.body,
                    priority=priority,
                    related_entity_id=related_entity_id,
                    status="sent",
                )
                notification_sent_total.labels(channel="email", status="sent").inc()
        except Exception as e:
            logger.error(f"Failed to send urgent notification for {event_type}: {e}", exc_info=True)
            await log_service.record(
                db,
                recipient=recipient,
                event_type=event_type,
                template_name=template_name,
                subject=None,
                body=None,
                priority=priority,
                related_entity_id=related_entity_id,
                status="failed",
                error=str(e),
            )
            notification_sent_total.labels(channel="email", status="failed").inc()
    elif not await template_store.is_enabled(db, template_name):
        await log_service.record(
            db, recipient=recipient, event_type=event_type, template_name=template_name,
            subject=None, body=None, priority=priority, related_entity_id=related_entity_id,
            status="skipped", error="template turned off in the Control Panel",
        )
    else:
        await digest_service.enqueue(
            db,
            recipient=recipient,
            event_type=event_type,
            template_name=template_name,
            template_context=context,
            related_entity_id=related_entity_id,
        )
        notification_sent_total.labels(channel="email", status="queued").inc()

    return priority
