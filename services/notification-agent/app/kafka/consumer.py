"""Kafka consumer for the Notification Agent.

Consumes every topic that names notification-agent as a consumer in
shared/schemas/events.md's "Consumed by" column. The task brief listed 8
of these; cross-checking the table against every row turned up two more
that also name notification-agent — document.classified and
vendor.offboarded — so all 10 are handled here:

  document.classified, license.usage.updated, approval.requested,
  approval.decided, contract.generated, contract.signed,
  contract.renewal.due, risk.score.updated, vendor.offboarded,
  notification.send
"""
import json
import asyncio
import logging

from aiokafka import AIOKafkaConsumer

from app.config import settings
from app.database import async_session_factory
from app.kafka.events import parse_envelope
from app.services import dispatcher, directory, routing, templating

logger = logging.getLogger(__name__)

CONSUME_TOPICS = [
    "document.classified",     # published by document-vendor-agent
    "license.usage.updated",   # published by approval-inventory-agent
    "approval.requested",      # published by approval-inventory-agent
    "approval.decided",        # published by approval-inventory-agent
    "contract.generated",      # published by contract-risk-agent
    "contract.signed",         # published by contract-risk-agent
    "contract.renewal.due",    # published by contract-risk-agent
    "risk.score.updated",      # published by contract-risk-agent
    "vendor.offboarded",       # published by contract-risk-agent
    "notification.send",       # generic fallback, published by any service
]


async def start_consumer(app):
    consumer = AIOKafkaConsumer(
        *CONSUME_TOPICS,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.kafka_consumer_group,
        auto_offset_reset="earliest",
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
    )

    try:
        await consumer.start()
        logger.info(f"Kafka consumer started, listening on: {CONSUME_TOPICS}")

        async for msg in consumer:
            try:
                event_type, payload, schema_version = parse_envelope(msg.value)
                if schema_version != 1:
                    logger.info(f"event {event_type} has schema_version={schema_version} (handled as v1-compatible)")

                handler = _HANDLERS.get(event_type)
                if handler is None:
                    logger.warning(f"Unhandled event type on topic {msg.topic}: {event_type}")
                    continue

                async with async_session_factory() as db:
                    await handler(db, payload)

            except Exception as e:
                logger.error(f"Error processing message: {e}", exc_info=True)

    except asyncio.CancelledError:
        logger.info("Kafka consumer loop cancelled")
    finally:
        await consumer.stop()
        logger.info("Kafka consumer stopped")


async def _handle_document_classified(db, payload: dict):
    # Only actionable when the extraction needs a human to look at it —
    # otherwise every successfully auto-classified document would fire an
    # email, which isn't useful signal.
    if not payload.get("needs_review"):
        return
    recipient = await directory.resolve_recipient(db, None)
    await dispatcher.notify(
        db,
        event_type="document.classified",
        template_name="document_classified",
        context=payload,
        recipient=recipient,
        related_entity_id=payload.get("document_id"),
    )


async def _handle_license_usage_updated(db, payload: dict):
    recipient = await directory.resolve_recipient(db, None)
    await dispatcher.notify(
        db,
        event_type="license.usage.updated",
        template_name="license_usage_updated",
        context=payload,
        recipient=recipient,
        related_entity_id=payload.get("license_id"),
    )


async def _handle_approval_requested(db, payload: dict):
    chain = payload.get("approval_chain") or []
    # The event doesn't say which chain index is "current" (that's tracked
    # internally by approval-inventory-agent) — the first entry is who a
    # freshly-created request needs to act on first.
    candidate = chain[0] if chain else None
    recipient = await directory.resolve_recipient(db, candidate)
    await dispatcher.notify(
        db,
        event_type="approval.requested",
        template_name="approval_requested",
        context=payload,
        recipient=recipient,
        related_entity_id=payload.get("request_id"),
    )


async def _handle_approval_decided(db, payload: dict):
    # approval.decided's payload has no requester contact field, only
    # request_id — look the requester up via the shared purchase_requests
    # table (see app/services/directory.py). The `escalated` flag is
    # surfaced in the rendered email body (app/templates/approval_decided.j2).
    requester = await directory.requester_for_request_id(db, payload.get("request_id"))
    recipient = await directory.resolve_recipient(db, requester)
    await dispatcher.notify(
        db,
        event_type="approval.decided",
        template_name="approval_decided",
        context=payload,
        recipient=recipient,
        related_entity_id=payload.get("request_id"),
    )


async def _handle_contract_generated(db, payload: dict):
    requester = await directory.requester_for_request_id(db, payload.get("purchase_request_id"))
    recipient = await directory.resolve_recipient(db, requester)
    await dispatcher.notify(
        db,
        event_type="contract.generated",
        template_name="contract_generated",
        context=payload,
        recipient=recipient,
        related_entity_id=payload.get("contract_id"),
    )


async def _handle_contract_signed(db, payload: dict):
    requester = await directory.requester_for_contract_id(db, payload.get("contract_id"))
    recipient = await directory.resolve_recipient(db, requester)
    await dispatcher.notify(
        db,
        event_type="contract.signed",
        template_name="contract_signed",
        context=payload,
        recipient=recipient,
        related_entity_id=payload.get("contract_id"),
    )


async def _handle_contract_renewal_due(db, payload: dict):
    requester = await directory.requester_for_contract_id(db, payload.get("contract_id"))
    recipient = await directory.resolve_recipient(db, requester)
    await dispatcher.notify(
        db,
        event_type="contract.renewal.due",
        template_name="contract_renewal_due",
        context=payload,
        recipient=recipient,
        related_entity_id=payload.get("contract_id"),
    )


async def _handle_risk_score_updated(db, payload: dict):
    recipient = await directory.resolve_recipient(db, None)
    await dispatcher.notify(
        db,
        event_type="risk.score.updated",
        template_name="risk_score_updated",
        context=payload,
        recipient=recipient,
        related_entity_id=payload.get("vendor_id"),
    )


async def _handle_vendor_offboarded(db, payload: dict):
    recipient = await directory.resolve_recipient(db, None)
    await dispatcher.notify(
        db,
        event_type="vendor.offboarded",
        template_name="vendor_offboarded",
        context=payload,
        recipient=recipient,
        related_entity_id=payload.get("vendor_id"),
    )


async def _handle_notification_send(db, payload: dict):
    """Generic fallback: any service can ask us to render+send an
    arbitrary template with arbitrary context. `priority` is authoritative
    here (urgent vs digest) — see app/services/routing.py."""
    raw_recipient = payload.get("recipient")
    recipient = directory.as_email(raw_recipient) if raw_recipient else await directory.resolve_recipient(db, None)
    # No `or "generic_fallback"` default here on purpose: that string is
    # also a real template filename, so a missing template_name would
    # take the "template_exists" branch below with an unwrapped context,
    # instead of the fallback-wrapper branch that actually supplies the
    # `template_name`/`context` variables generic_fallback.j2 expects.
    requested_template = payload.get("template_name")
    template_context = payload.get("template_context") or {}

    if requested_template and templating.template_exists(requested_template):
        template_name = requested_template
        context = template_context
    else:
        template_name = "generic_fallback"
        context = {"template_name": requested_template or "(none specified)", "context": template_context}

    priority = routing.decide_priority("notification.send", payload)

    await dispatcher.notify(
        db,
        event_type="notification.send",
        template_name=template_name,
        context=context,
        recipient=recipient,
        related_entity_id=payload.get("related_entity_id"),
        priority_override=priority,
    )


_HANDLERS = {
    "document.classified": _handle_document_classified,
    "license.usage.updated": _handle_license_usage_updated,
    "approval.requested": _handle_approval_requested,
    "approval.decided": _handle_approval_decided,
    "contract.generated": _handle_contract_generated,
    "contract.signed": _handle_contract_signed,
    "contract.renewal.due": _handle_contract_renewal_due,
    "risk.score.updated": _handle_risk_score_updated,
    "vendor.offboarded": _handle_vendor_offboarded,
    "notification.send": _handle_notification_send,
}
