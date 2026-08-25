"""The single entry point every Kafka handler in app/kafka/consumer.py
calls: decide urgent-vs-digest, then either render+send+log immediately,
or queue for the next digest flush."""
import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import routing, templating, email_service, log_service, digest_service

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
            subject, body = templating.render_template(template_name, context)
            await email_service.send_email(recipient, subject, body)
            await log_service.record(
                db,
                recipient=recipient,
                event_type=event_type,
                template_name=template_name,
                subject=subject,
                body=body,
                priority=priority,
                related_entity_id=related_entity_id,
                status="sent",
            )
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
    else:
        await digest_service.enqueue(
            db,
            recipient=recipient,
            event_type=event_type,
            template_name=template_name,
            template_context=context,
            related_entity_id=related_entity_id,
        )

    return priority
