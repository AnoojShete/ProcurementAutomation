"""
Kafka consumer for the Approval & Inventory Intelligence Agent.

Consumes events from document.classified and contract.signed topics.
These are events published by other services that this agent reacts to.
"""
import json
import asyncio
import logging
from aiokafka import AIOKafkaConsumer
from sqlalchemy import select
from app.config import settings
from app.database import async_session_factory
from app.models import PurchaseRequest, Contract, License, ProcessedEvent, Inventory

from shared.infra.retry import with_retry
from shared.logging.context import CorrelationContext

logger = logging.getLogger(__name__)

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
    )

    try:
        await with_retry(consumer.start, name="Kafka consumer")
        logger.info(f"Kafka consumer started, listening on: {CONSUME_TOPICS}")

        async for msg in consumer:
            try:
                event = msg.value
                correlation_id = event.get("correlation_id")
                if correlation_id:
                    CorrelationContext.set(correlation_id)
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
                    logger.warning(f"Unknown event type on topic {msg.topic}: {event_type}")

            except Exception as e:
                logger.error(f"Error processing message: {e}", exc_info=True)

    except asyncio.CancelledError:
        logger.info("Kafka consumer loop cancelled")
    finally:
        await consumer.stop()
        logger.info("Kafka consumer stopped")


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


async def _mark_processed(session, event_id: str, topic: str):
    from datetime import datetime, timezone
    stmt = ProcessedEvent(event_id=event_id, topic=topic, processed_at=datetime.now(timezone.utc))
    session.add(stmt)

async def _handle_contract_signed(payload: dict, event: dict):
    """Handle a contract.signed event.
    
    Marks the associated purchase request 'fulfilled'
    when the downstream contract is fully executed.
    """
    event_id = event.get("event_id")
    contract_id = payload.get("contract_id")
    signed_by = payload.get("signed_by")
    signed_at = payload.get("signed_at")

    logger.info(f"Contract signed: id={contract_id}, by={signed_by} at {signed_at}")

    async with async_session_factory() as session:
        try:
            # 1. Look up the contract to find the associated purchase_request_id
            stmt = select(Contract).where(Contract.id == contract_id)
            result = await session.execute(stmt)
            contract = result.scalar_one_or_none()

            if not contract or not contract.purchase_request_id:
                logger.info(
                    f"No purchase request linked to contract {contract_id} — nothing to update"
                )
                # Still mark as processed so we don't retry forever
                if event_id:
                    await _mark_processed(session, event_id, "contract.signed")
                    await session.commit()
                return

            purchase_request_id = contract.purchase_request_id

            # 2. Fetch the purchase request to inspect its type and items
            req_stmt = select(PurchaseRequest).where(
                PurchaseRequest.id == purchase_request_id
            )
            req_result = await session.execute(req_stmt)
            req = req_result.scalar_one_or_none()

            if not req:
                logger.warning(
                    f"Purchase request {purchase_request_id} not found "
                    f"for contract {contract_id}"
                )
                if event_id:
                    await _mark_processed(session, event_id, "contract.signed")
                    await session.commit()
                return

            # 3. Mark the purchase request as fulfilled
            req.status = "fulfilled"
            logger.info(
                f"Purchase request {purchase_request_id} marked 'fulfilled' "
                f"after contract {contract_id} signed"
            )

            # 4. Activate the license if this is a license or saas procurement
            if req.request_type in ("license", "saas"):
                activated = await _activate_license_for_request(session, req, contract)
                if activated:
                    logger.info(
                        f"License activated for {req.request_type} request "
                        f"{purchase_request_id}"
                    )
                else:
                    logger.warning(
                        f"No license found to activate for {req.request_type} "
                        f"request {purchase_request_id}"
                    )

            # GAP-A7: handle hardware fulfillment — decrement reserved_quantity
            # to reflect physical delivery/allocation.
            elif req.request_type == "hardware":
                await _fulfill_hardware_inventory(session, req)

            # 5. Mark as processed in the SAME transaction
            if event_id:
                await _mark_processed(session, event_id, "contract.signed")

            await session.commit()

        except Exception as e:
            logger.error(
                f"Failed to process contract.signed for contract {contract_id}: {e}",
                exc_info=True
            )
            await session.rollback()


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
    """Handle an invoice.matched event from document-vendor-agent.
    Updates the purchase_request status to 'invoice_received'.
    """
    purchase_request_id = payload.get("purchase_request_id")
    if not purchase_request_id:
        return

    logger.info(f"Received invoice.matched for purchase_request {purchase_request_id}")
    async with async_session_factory() as session:
        try:
            stmt = select(PurchaseRequest).where(PurchaseRequest.id == purchase_request_id)
            result = await session.execute(stmt)
            req = result.scalar_one_or_none()
            if req:
                req.status = "invoice_received"
                logger.info(f"Purchase request {purchase_request_id} updated to 'invoice_received'")
                event_id = event.get("event_id")
                if event_id:
                    await _mark_processed(session, event_id, "invoice.matched")
                await session.commit()
            else:
                logger.warning(f"Purchase request {purchase_request_id} not found for invoice.matched")
        except Exception as e:
            logger.error(f"Error handling invoice.matched: {e}", exc_info=True)
            await session.rollback()


async def _handle_business_rule_updated(payload: dict, event: dict):
    """Handle a business_rule.updated event from auth-service.
    Invalidates the local cached rule.
    """
    rule_key = payload.get("rule_key")
    if rule_key:
        from shared.rules_engine import invalidate_rule
        invalidate_rule(rule_key)
        logger.info(f"Invalidated local rules_engine cache for key: {rule_key}")
