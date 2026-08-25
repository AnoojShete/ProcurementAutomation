"""Kafka consumer for the Document & Vendor Intelligence Agent's background
worker (app/worker.py). Consumes document.ingested — published by this
same service's POST /documents/upload — and runs the extraction pipeline.
"""
import json
import asyncio
import logging

from aiokafka import AIOKafkaConsumer
from app.config import settings
from app.database import async_session_factory
from app.services.document_service import process_document

logger = logging.getLogger(__name__)

CONSUME_TOPICS = [
    "document.ingested",  # published by this service's own API process
]


async def start_consumer(kafka_producer):
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

                if event_type == "document.ingested":
                    await _handle_document_ingested(kafka_producer, payload)
                else:
                    logger.warning(f"Unknown event type on topic {msg.topic}: {event_type}")

            except Exception as e:
                logger.error(f"Error processing message: {e}", exc_info=True)

    except asyncio.CancelledError:
        logger.info("Kafka consumer loop cancelled")
    finally:
        await consumer.stop()
        logger.info("Kafka consumer stopped")


async def _handle_document_ingested(kafka_producer, payload: dict):
    document_id = payload.get("document_id")
    logger.info(f"document.ingested received, running extraction pipeline: document_id={document_id}")
    async with async_session_factory() as db:
        await process_document(db, kafka_producer, document_id)
