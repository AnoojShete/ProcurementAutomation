"""
Kafka consumer for the Approval & Inventory Intelligence Agent.

Consumes events from external services only:
  - document.classified  (from document-vendor-agent)
  - contract.signed      (from contract-risk-agent)

This service PUBLISHES license.usage.updated — it must NOT consume it.
The usage computation is driven by raw SSO login data (from the synthetic
generator script), not from the event this service itself emits.

Data flow for license utilisation:
  1. scripts/generate_sso_logs.py → data/synthetic-sso-logs/sso_login_events.json
  2. Periodic background task (main.py) reads that file → writes to license_usage table
  3. UsageService.check_and_trigger_reclaims() → publishes license.usage.updated
"""
import json
import asyncio
import logging
from aiokafka import AIOKafkaConsumer
from sqlalchemy import select, update
from app.config import settings
from app.database import async_session_factory
from app.models import PurchaseRequest, Contract, License

logger = logging.getLogger(__name__)

# Topics this service consumes — license.usage.updated is intentionally
# NOT here because we publish that topic, not consume it.
CONSUME_TOPICS = [
    "document.classified",  # Published by document-vendor-agent
    "contract.signed",      # Published by contract-risk-agent
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
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
    )

    try:
        await consumer.start()
        logger.info(f"Kafka consumer started, listening on: {CONSUME_TOPICS}")

        async for msg in consumer:
            try:
                event = msg.value
                event_type = event.get("event_type")
                payload = event.get("payload", {})

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


async def _handle_contract_signed(payload: dict, event: dict):
    """Handle a contract.signed event.
    
    Per the shared schema, this triggers two actions:
      1. Mark the associated purchase_request as 'fulfilled' — the procurement
         cycle is complete once the contract is executed.
      2. Activate the corresponding license row (for license/saas requests) —
         the license is now live and should be tracked for utilisation.
    
    Payload fields (per shared/schemas/events.md):
      contract_id, signed_at, signed_by, esign_provider_ref
    """
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
                return

            # 3. Mark the purchase request as fulfilled
            req.status = "fulfilled"
            logger.info(
                f"Purchase request {purchase_request_id} marked 'fulfilled' "
                f"after contract {contract_id} signed"
            )

            # 4. Activate the license if this is a license or saas procurement.
            #    The license to activate is identified by:
            #      a) vendor_id on the contract, or
            #      b) a license_id embedded in req.items JSON
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
