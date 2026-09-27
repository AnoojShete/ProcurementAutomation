"""
Kafka consumer for the Approval & Inventory Intelligence Agent.

Consumes events from document.classified and contract.signed topics.
These are events published by other services that this agent reacts to.
"""
import json
import asyncio
import logging
from aiokafka import AIOKafkaConsumer
from shared.kafka_security import kafka_auth_kwargs
from sqlalchemy import select
from app.config import settings
from app.database import async_session_factory
from app.models import PurchaseRequest, Contract, License, Inventory

from shared.eventing import deliver, PermanentEventError
from shared.infra.retry import with_retry
from shared.lifecycle import already_past, can_transition
from shared.logging.context import CorrelationContext

logger = logging.getLogger(__name__)

CONSUMER_NAME = "approval-inventory-agent"

# Topics this service consumes (from shared/kafka-topics.yaml)
CONSUME_TOPICS = [
    "document.classified",  # Published by document-vendor-agent
    "contract.signed",      # Published by contract-risk-agent
    "invoice.matched",      # Published by document-vendor-agent
    "business_rule.updated",# Published by auth-service
]


async def start_consumer(app):
    """Background task that consumes Kafka events.
    
    Runs as an asyncio task during the FastAPI app lifespan.
    Handles graceful shutdown via CancelledError.
    """
    consumer = AIOKafkaConsumer(
        *CONSUME_TOPICS,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.kafka_consumer_group,
        auto_offset_reset="earliest",
        session_timeout_ms=60000,
        heartbeat_interval_ms=10000,
        max_poll_interval_ms=600000,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        **kafka_auth_kwargs(),
    )

    try:
        await with_retry(consumer.start, name="Kafka consumer")
        logger.info(f"Kafka consumer started, listening on: {CONSUME_TOPICS}")

        async for msg in consumer:
            event = msg.value
            correlation_id = event.get("correlation_id")
            if correlation_id:
                CorrelationContext.set(correlation_id)
            # Retries, then dead-letters to event_dlq instead of dropping
            # the event (shared/eventing/inbox.py).
            await deliver(
                async_session_factory, CONSUMER_NAME, msg.topic, event,
                lambda event=event, topic=msg.topic: dispatch(topic, event),
            )

    except asyncio.CancelledError:
        logger.info("Kafka consumer loop cancelled")
    finally:
        await consumer.stop()
        logger.info("Kafka consumer stopped")


async def dispatch(topic: str, event: dict) -> None:
    """Routes one event to its handler. Raises on failure so deliver() can
    retry / dead-letter it; also used to replay DLQ entries."""
    event_type = event.get("event_type")
    payload = event.get("payload", {})
    if event_type == "document.classified":
        await _handle_document_classified(payload, event)
    elif event_type == "contract.signed":
        await _handle_contract_signed(payload, event)
    elif event_type == "invoice.matched":
        await _handle_invoice_matched(payload, event)
    elif event_type == "business_rule.updated":
        await _handle_business_rule_updated(payload, event)
    else:
        logger.warning(f"Unknown event type on topic {topic}: {event_type}")


async def _handle_document_classified(payload: dict, event: dict):
    """Handle a document.classified event.
    
    Logs the event for audit. Could also trigger automatic purchase request
    creation based on classified document data.
    """
    document_id = payload.get("document_id")
    document_type = payload.get("document_type")
    vendor_name = payload.get("vendor_name_raw")
    confidence = payload.get("overall_confidence", 0)

    logger.info(
        f"Document classified: id={document_id}, type={document_type}, "
        f"vendor={vendor_name}, confidence={confidence}"
    )


async def _handle_contract_signed(payload: dict, event: dict):
    """Marks the purchase request 'fulfilled' once its contract is signed.
    Raises on failure so the event is retried / dead-lettered rather than
    lost (which is how requests used to get stuck at 'approved')."""
    contract_id = payload.get("contract_id")
    logger.info(f"Contract signed: id={contract_id}, by={payload.get('signed_by')} at {payload.get('signed_at')}")
    if not contract_id:
        raise PermanentEventError("contract.signed payload has no contract_id")
    async with async_session_factory() as session:
        outcome = await apply_contract_signed(session, contract_id)
        await session.commit()
    logger.info(f"contract.signed for {contract_id}: {outcome}")


FULFILMENT_MARKER = "contract_fulfilment_applied"


async def apply_contract_signed(session, contract_id: str, source: str = "contract.signed") -> str:
    """The effect of a signed contract on its purchase request, shared by
    the Kafka handler and the reconciler. Caller commits.

    Two parts, each applied at most once:
      - status: approved -> fulfilled. If an invoice already moved the
        request further (partially_invoiced / invoice_received), the status
        stays where it is — the lifecycle never goes backwards.
      - fulfilment: license activation / hardware stock release. Tracked by
        an audit_log marker rather than by status, so it still happens when
        the invoice beat the signature, and never twice.
    """
    from datetime import datetime, timezone
    import uuid as _uuid
    from app.models import AuditLog

    contract = (await session.execute(select(Contract).where(Contract.id == contract_id))).scalar_one_or_none()
    if contract is None:
        # The contract row is written before contract.signed is published,
        # so a missing row is worth a retry (replica lag, ordering).
        raise LookupError(f"contract {contract_id} not found")
    if not contract.purchase_request_id:
        return "no_request"

    req = (
        await session.execute(select(PurchaseRequest).where(PurchaseRequest.id == contract.purchase_request_id))
    ).scalar_one_or_none()
    if req is None:
        raise PermanentEventError(f"purchase request {contract.purchase_request_id} for contract {contract_id} not found")

    moved_on = already_past(req.status, "fulfilled")
    if not moved_on and not can_transition(req.status, "fulfilled"):
        raise PermanentEventError(
            f"contract {contract_id} signed but request {req.id} is '{req.status}' — cannot fulfil"
        )

    fulfilled_before = (
        await session.execute(
            select(AuditLog.id).where(AuditLog.entity_id == req.id, AuditLog.action == FULFILMENT_MARKER).limit(1)
        )
    ).first() is not None

    outcome = []
    now = datetime.now(timezone.utc)
    if not moved_on and req.status != "fulfilled":
        req.status = "fulfilled"
        req.updated_at = now
        outcome.append("fulfilled")
    if not fulfilled_before:
        if req.request_type in ("license", "saas"):
            if not await _activate_license_for_request(session, req, contract):
                logger.warning(f"No license found to activate for {req.request_type} request {req.id}")
        elif req.request_type == "hardware":
            await _fulfill_hardware_inventory(session, req)
        session.add(AuditLog(
            id=str(_uuid.uuid4()), entity_type="purchase_request", entity_id=req.id, action=FULFILMENT_MARKER,
            performed_by=source, created_at=now, details={"contract_id": str(contract_id), "status": req.status},
        ))
        outcome.append("fulfilment_applied")
    result = "+".join(outcome) or f"already_{req.status}"
    logger.info(f"contract.signed effect for request {req.id} ({source}): {result}")
    return result


async def _activate_license_for_request(session, req: PurchaseRequest, contract) -> bool:
    """Activate the license row associated with a fulfilled license/saas request.
    
    Search strategy (in order):
      1. A license_id embedded in req.items JSON (most precise).
      2. Any inactive license for the same vendor as the contract.
    
    Sets License.status = 'active' so the utilisation scanner will start
    tracking it in the next scan cycle.
    
    Returns True if a license was activated, False if none was found.
    """
    items = req.items or []

    # Only line items tagged category 'software' should ever be eligible to produce a license record
    if items:
        categories = [item.get("category") for item in items if item.get("category")]
        if categories and not any(c == "software" for c in categories):
            logger.info(f"Skipping license activation for request {req.id}: no items with category 'software'")
            return False

    # Strategy 1: items JSON may contain {"license_id": "uuid"}
    for item in items:
        license_id = item.get("license_id")
        if license_id:
            lic_stmt = select(License).where(License.id == license_id)
            lic_result = await session.execute(lic_stmt)
            lic = lic_result.scalar_one_or_none()
            if lic:
                lic.status = "active"
                logger.info(
                    f"Activated license {lic.id} ({lic.app_name}) from items JSON"
                )
                return True

    # Strategy 2: find any inactive license from the same vendor
    vendor_id = contract.vendor_id or req.vendor_id
    if vendor_id:
        lic_stmt = (
            select(License)
            .where(License.vendor_id == vendor_id)
            .where(License.status != "active")
        )
        lic_result = await session.execute(lic_stmt)
        lic = lic_result.scalars().first()
        if lic:
            lic.status = "active"
            logger.info(
                f"Activated license {lic.id} ({lic.app_name}) by vendor match"
            )
            return True

    return False


async def _fulfill_hardware_inventory(session, req: PurchaseRequest) -> None:
    """GAP-A7: Handle hardware fulfillment when a contract is signed.

    When a hardware purchase contract is signed, the physical goods are
    considered delivered.  We decrement reserved_quantity (goods are no
    longer just 'reserved' — they've been shipped/allocated) and leave
    available_quantity as-is (new stock hasn't arrived yet).

    Each item in req.items must carry a 'sku' and 'quantity' key.
    Items without a matching Inventory row are skipped with a warning.
    """
    items = req.items or []
    for item in items:
        sku = item.get("sku")
        qty = item.get("quantity", 0)
        if not sku or qty <= 0:
            continue

        stmt = select(Inventory).where(Inventory.sku == sku)
        result = await session.execute(stmt)
        inv = result.scalar_one_or_none()

        if not inv:
            logger.warning(
                f"Inventory row not found for SKU {sku} "
                f"(contract fulfilment for request {req.id})"
            )
            continue

        # Clamp: never go below zero
        to_release = min(inv.reserved_quantity, qty)
        inv.reserved_quantity -= to_release
        logger.info(
            f"Hardware fulfilled: released {to_release}x {sku} from reserved_quantity "
            f"(request {req.id})"
        )


async def _handle_invoice_matched(payload: dict, event: dict):
    """invoice.matched from document-vendor-agent. The invoice ledger
    (POST /requests/match-invoice, app/services/invoice_ledger.py) already
    allocated the invoice and moved the request inside its own
    transaction; this handler only covers events from producers that
    predate the ledger, and never forces an illegal transition."""
    purchase_request_id = payload.get("purchase_request_id")
    document_id = payload.get("document_id")
    if not purchase_request_id:
        raise PermanentEventError("invoice.matched payload has no purchase_request_id")

    from sqlalchemy import text
    async with async_session_factory() as session:
        booked = (
            await session.execute(
                text("SELECT 1 FROM invoice_allocations WHERE document_id = :d LIMIT 1"), {"d": document_id}
            )
        ).first() if document_id else None
        if booked:
            logger.info(f"invoice.matched for {purchase_request_id}: already booked by the ledger")
            return

        req = (
            await session.execute(select(PurchaseRequest).where(PurchaseRequest.id == purchase_request_id))
        ).scalar_one_or_none()
        if req is None:
            raise PermanentEventError(f"purchase request {purchase_request_id} not found")
        if not can_transition(req.status, "invoice_received"):
            raise PermanentEventError(
                f"invoice matched to request {purchase_request_id} in status '{req.status}'"
            )
        req.status = "invoice_received"
        await session.commit()
        logger.info(f"Purchase request {purchase_request_id} updated to 'invoice_received'")


async def _handle_business_rule_updated(payload: dict, event: dict):
    """Handle a business_rule.updated event from auth-service.
    Invalidates the local cached rule.
    """
    rule_key = payload.get("rule_key")
    if rule_key:
        from shared.rules_engine import invalidate_rule
        invalidate_rule(rule_key)
        logger.info(f"Invalidated local rules_engine cache for key: {rule_key}")
