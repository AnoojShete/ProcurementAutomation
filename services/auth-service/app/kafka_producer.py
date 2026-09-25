import os
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from aiokafka import AIOKafkaProducer

logger = logging.getLogger(__name__)

TOPIC_BUSINESS_RULE_UPDATED = "business_rule.updated"

_producer: Optional[AIOKafkaProducer] = None


async def start_kafka_producer():
    global _producer
    bootstrap = os.environ.get(
        "KAFKA_BOOTSTRAP_SERVERS",
        os.environ.get("APP_KAFKA_BOOTSTRAP_SERVERS", "redpanda:9092"),
    )
    try:
        _producer = AIOKafkaProducer(
            bootstrap_servers=bootstrap,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
        await _producer.start()
        logger.info(f"Kafka producer started on {bootstrap}")
    except Exception as e:
        logger.warning(f"Could not connect Kafka producer on {bootstrap}: {e}")
        _producer = None


async def stop_kafka_producer():
    global _producer
    if _producer:
        try:
            await _producer.stop()
        except Exception:
            pass
        _producer = None


async def publish_business_rule_updated(rule_key: str, new_value: Any, changed_by: Optional[str], changed_at: str):
    global _producer
    event = {
        "event_id": str(uuid.uuid4()),
        "correlation_id": str(uuid.uuid4()),
        "event_type": TOPIC_BUSINESS_RULE_UPDATED,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source_service": "auth-service",
        "payload": {
            "rule_key": rule_key,
            "new_value": new_value,
            "changed_by": changed_by,
            "changed_at": changed_at,
        },
    }
    if _producer:
        try:
            await _producer.send_and_wait(TOPIC_BUSINESS_RULE_UPDATED, event)
            logger.info(f"Published {TOPIC_BUSINESS_RULE_UPDATED} for {rule_key}")
        except Exception as e:
            logger.error(f"Failed to publish {TOPIC_BUSINESS_RULE_UPDATED}: {e}")
    else:
        logger.info(f"Kafka producer not active; simulated publish {TOPIC_BUSINESS_RULE_UPDATED} for {rule_key}")
