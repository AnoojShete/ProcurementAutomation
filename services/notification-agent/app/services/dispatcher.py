"""The single entry point every Kafka handler in app/kafka/consumer.py
calls: decide urgent-vs-digest, enforce privacy controls (suppression,
minimisation, cross-border checks), then either render+send+log immediately,
or queue for the next digest flush."""
import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import (
    routing,
    template_store,
    email_service,
    log_service,
    digest_service,
    privacy_service,
)
from app.metrics import notification_sent_total
from shared.rules_engine import get_rule

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
    recipient_country: Optional[str] = None,
) -> str:
    """Route + deliver one notification with Prompt 12B privacy governance.
    Returns the priority it was sent at ("urgent" or "digest")."""
    priority = priority_override or routing.decide_priority(event_type, context)

    # 1. Render template
    email = await template_store.render(db, template_name, context)
    category = email.category or "transactional"
    primary_to = email.recipient if (email.recipient and email.recipient.strip()) else recipient

    # 2. Check email suppression list
    suppressed, supp_reason = await privacy_service.is_suppressed(db, primary_to, category=category)
    if suppressed:
        logger.info(f"[PRIVACY] Email to {primary_to} suppressed (reason: {supp_reason})")
        await log_service.record(
            db, recipient=primary_to, event_type=event_type, template_name=template_name,
            subject=email.subject, body=None, priority=priority, related_entity_id=related_entity_id,
            status="suppressed", error=f"Suppressed: {supp_reason}",
        )
        return priority

    # 3. Check cross-border processor compliance
    allowed_xfer, xfer_err = await privacy_service.check_cross_border_transfer(
        db, recipient_country, category=category
    )
    if not allowed_xfer:
        logger.warning(f"[PRIVACY] Cross-border check blocked email to {primary_to}: {xfer_err}")
        await log_service.record(
            db, recipient=primary_to, event_type=event_type, template_name=template_name,
            subject=email.subject, body=None, priority=priority, related_entity_id=related_entity_id,
            status="blocked", error=xfer_err,
        )
        return priority

    # 4. Delivery logic
    if priority == routing.URGENT:
        try:
            if not email.enabled:
                await log_service.record(
                    db, recipient=primary_to, event_type=event_type, template_name=template_name,
                    subject=None, body=None, priority=priority, related_entity_id=related_entity_id,
                    status="skipped", error="template turned off in the Control Panel",
                )
                return priority

            store_bodies = get_rule("privacy.store_email_bodies", False)
            body_to_store = email.body if store_bodies else None

            # Primary recipient + copies
            recipients = [primary_to] + [r for r in email.extra_recipients if r != primary_to]
            for to in recipients:
                # Per-recipient suppression check
                is_supp, reason = await privacy_service.is_suppressed(db, to, category=category)
                if is_supp:
                    await log_service.record(
                        db, recipient=to, event_type=event_type, template_name=template_name,
                        subject=email.subject, body=None, priority=priority, related_entity_id=related_entity_id,
                        status="suppressed", error=f"Suppressed: {reason}",
                    )
                    continue

                await email_service.send_email(
                    to, email.subject, email.body, db=db, category=category
                )
                await log_service.record(
                    db,
                    recipient=to,
                    event_type=event_type,
                    template_name=template_name,
                    subject=email.subject,
                    body=body_to_store,
                    priority=priority,
                    related_entity_id=related_entity_id,
                    status="sent",
                )
                notification_sent_total.labels(channel="email", status="sent").inc()
        except Exception as e:
            logger.error(f"Failed to send urgent notification for {event_type}: {e}", exc_info=True)
            await log_service.record(
                db,
                recipient=primary_to,
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
            db, recipient=primary_to, event_type=event_type, template_name=template_name,
            subject=None, body=None, priority=priority, related_entity_id=related_entity_id,
            status="skipped", error="template turned off in the Control Panel",
        )
    else:
        await digest_service.enqueue(
            db,
            recipient=primary_to,
            event_type=event_type,
            template_name=template_name,
            template_context=context,
            related_entity_id=related_entity_id,
        )
        notification_sent_total.labels(channel="email", status="queued").inc()

    return priority
