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
from app.models import PurchaseRequest

logger = logging.getLogger(__name__)

# Topics this service consumes (from shared/kafka-topics.yaml)
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
    """Handle a contract.signed event.
    
    Updates the associated purchase request status to 'contract_signed'
    when the downstream contract is fully executed.
    """
    contract_id = payload.get("contract_id")
    signed_by = payload.get("signed_by")

    logger.info(f"Contract signed: id={contract_id}, by={signed_by}")

    # The contract.signed payload has contract_id, not a direct request_id.
    # In a full implementation, you'd look up the contract to find the
    # associated purchase_request_id. For now, we log it.
