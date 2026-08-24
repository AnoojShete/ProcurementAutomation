"""
Kafka consumer for the Approval & Inventory Intelligence Agent.

Consumes events from external services only:
  - document.classified  (from document-vendor-agent)
  - contract.signed      (from contract-risk-agent)

This service PUBLISHES license.usage.updated — it must NOT consume it.

Idempotency (Issue 6):
  Every inbound event is checked against the processed_events table
  before being handled.  If the event_id has already been processed,
  the message is silently skipped.  This protects against Kafka's
  at-least-once redelivery semantics.
"""
import json
import asyncio
import logging
from datetime import datetime, timezone
from aiokafka import AIOKafkaConsumer
from sqlalchemy import select, update
from app.config import settings
from app.database import async_session_factory
from app.models import PurchaseRequest, Contract, License, ProcessedEvent

logger = logging.getLogger(__name__)

# Topics this service consumes — license.usage.updated is intentionally
# NOT here because we publish that topic, not consume it.
CONSUME_TOPICS = [
    "document.classified",  # Published by document-vendor-agent
    "contract.signed",      # Published by contract-risk-agent
]


# ── Idempotency helpers ─────────────────────────────────────────────────

async def _is_already_processed(session, event_id: str) -> bool:
    """Check if an event_id has already been processed."""
    stmt = select(ProcessedEvent).where(ProcessedEvent.event_id == event_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none() is not None


async def _mark_processed(session, event_id: str, event_type: str):
    """Record that an event has been successfully processed."""
    record = ProcessedEvent(
        event_id=event_id,
        event_type=event_type,
        processed_at=datetime.now(timezone.utc),
    )
    session.add(record)
    # Committed by the caller along with the business transaction


# ── Consumer loop ────────────────────────────────────────────────────────

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
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
    )

    try:
        await consumer.start()
        logger.info(f"Kafka consumer started, listening on: {CONSUME_TOPICS}")

        async for msg in consumer:
            try:
                event = msg.value
                event_id = event.get("event_id")
                event_type = event.get("event_type")
                payload = event.get("payload", {})

                # ── Idempotency check (Issue 6) ─────────────────────
                if event_id:
                    async with async_session_factory() as dedup_session:
                        if await _is_already_processed(dedup_session, event_id):
                            logger.info(
                                f"Skipping already-processed event {event_id} "
                                f"(type={event_type})"
                            )
                            continue

                # ── Dispatch ─────────────────────────────────────────
                if event_type == "document.classified":
                    await _handle_document_classified(payload, event)

                elif event_type == "contract.signed":
                    await _handle_contract_signed(payload, event)

                else:
                    logger.warning(f"Unknown event type on topic {msg.topic}: {event_type}")

            except Exception as e:
                logger.error(f"Error processing message: {e}", exc_info=True)

    except asyncio.CancelledError:
        logger.info("Kafka consumer loop cancelled")
    finally:
        await consumer.stop()
        logger.info("Kafka consumer stopped")


# ── Handlers ─────────────────────────────────────────────────────────────

async def _handle_document_classified(payload: dict, event: dict):
    """Handle a document.classified event.
    
    Logs the classified document for audit. In a full implementation,
    this could automatically create a purchase request from a classified PO.
    """
    document_id = payload.get("document_id")
    document_type = payload.get("document_type")
    vendor_name = payload.get("vendor_name_raw")
    confidence = payload.get("overall_confidence", 0)

    logger.info(
        f"Document classified: id={document_id}, type={document_type}, "
        f"vendor={vendor_name}, confidence={confidence}"
    )

    # Mark as processed (document.classified is mostly audit/logging,
    # but we still track it for idempotency)
    event_id = event.get("event_id")
    if event_id:
        async with async_session_factory() as session:
            await _mark_processed(session, event_id, "document.classified")
            await session.commit()


async def _handle_contract_signed(payload: dict, event: dict):
    """Handle a contract.signed event.
    
    Per the shared schema, this triggers two actions:
      1. Mark the associated purchase_request as 'fulfilled'.
      2. Activate the corresponding license row (for license/saas requests).
    
    The idempotency record is written in the SAME transaction as the
    business update, so either both succeed or neither does.
    """
    contract_id = payload.get("contract_id")
    signed_by = payload.get("signed_by")
    signed_at = payload.get("signed_at")
    event_id = event.get("event_id")

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
