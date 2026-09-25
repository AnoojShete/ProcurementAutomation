"""Kafka consumer for the Contract & Risk Analysis Agent.

Consumes vendor.matched (document-vendor-agent) and approval.decided
(approval-inventory-agent) per shared/schemas/events.md's "Consumed by"
column for this service.
"""
import json
import asyncio
import logging

from aiokafka import AIOKafkaConsumer
from app.config import settings
from app.database import async_session_factory
from app.services.contract_service import generate_contract_for_request
from app.services.risk_service import score_vendor

from shared.infra.retry import with_retry
from shared.logging.context import CorrelationContext

logger = logging.getLogger(__name__)

CONSUME_TOPICS = [
    "vendor.matched",     # published by document-vendor-agent
    "approval.decided",   # published by approval-inventory-agent
    "business_rule.updated", # published by auth-service
]


async def start_consumer(app):
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

                if event_type == "vendor.matched":
                    await _handle_vendor_matched(app, payload)
                elif event_type == "approval.decided":
                    await _handle_approval_decided(app, payload)
                elif event_type == "business_rule.updated":
                    rule_key = payload.get("rule_key")
                    if rule_key:
                        from shared.rules_engine import invalidate_rule
                        invalidate_rule(rule_key)
                        logger.info(f"Invalidated local rules_engine cache for key: {rule_key}")
                else:
                    logger.warning(f"Unknown event type on topic {msg.topic}: {event_type}")

            except Exception as e:
                logger.error(f"Error processing message: {e}", exc_info=True)

    except asyncio.CancelledError:
        logger.info("Kafka consumer loop cancelled")
    finally:
        await consumer.stop()
        logger.info("Kafka consumer stopped")


async def _handle_vendor_matched(app, payload: dict):
    """A newly-matched vendor gets an initial risk score so the frontend
    has something to show as soon as the vendor exists."""
    if payload.get("match_type") != "new":
        return
    vendor_id = payload.get("vendor_id")
    logger.info(f"New vendor matched, scoring: vendor_id={vendor_id}")
    async with async_session_factory() as db:
        await score_vendor(db, app.state.kafka_producer, vendor_id)


async def _handle_approval_decided(app, payload: dict):
    """An approved purchase request is ready for a contract."""
    if payload.get("decision") != "approved":
        return
    request_id = payload.get("request_id")
    logger.info(f"Request approved, generating contract: request_id={request_id}")
    async with async_session_factory() as db:
        try:
            await generate_contract_for_request(db, app.state.kafka_producer, request_id, template_name=None)
        except Exception as e:
            logger.error(f"Could not auto-generate contract for {request_id}: {e}")
