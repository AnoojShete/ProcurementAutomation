"""
Kafka event producer for the Approval & Inventory Intelligence Agent.

Publishes events to the exact topic names defined in shared/kafka-topics.yaml.
Each event is wrapped in the standard envelope from shared/schemas/events.md.
"""
import json
import logging
from datetime import datetime, timezone
from aiokafka import AIOKafkaProducer
from app.kafka.events import (
    build_event,
    build_approval_requested_payload,
    build_approval_decided_payload,
    build_license_usage_updated_payload
)

logger = logging.getLogger(__name__)

# Topic names must match shared/kafka-topics.yaml exactly
TOPIC_APPROVAL_REQUESTED = "approval.requested"
TOPIC_APPROVAL_DECIDED = "approval.decided"
TOPIC_LICENSE_USAGE_UPDATED = "license.usage.updated"
TOPIC_NOTIFICATION_SEND = "notification.send"


class KafkaEventProducer:
    """Async Kafka producer that publishes domain events.
    
    Usage:
        producer = KafkaEventProducer("kafka:9092")
        await producer.start()
        await producer.publish_approval_requested(request)
        await producer.stop()
    """

    def __init__(self, bootstrap_servers: str):
        self.producer = AIOKafkaProducer(
            bootstrap_servers=bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            acks="all",  # Wait for all replicas to acknowledge
        )
        self.service_name = "approval-inventory-agent"

    async def start(self):
        """Start the underlying Kafka producer."""
        await self.producer.start()
        logger.info("Kafka producer started")

    async def stop(self):
        """Gracefully stop the Kafka producer."""
        await self.producer.stop()
        logger.info("Kafka producer stopped")

    async def publish(self, topic: str, event: dict):
        """Publish a pre-built event to a Kafka topic."""
        await self.producer.send_and_wait(topic, event)
        logger.info(f"Published event {event.get('event_type')} to {topic}")

    async def publish_approval_requested(self, request):
        """Publish an approval.requested event from a PurchaseRequest ORM object."""
        payload = build_approval_requested_payload(
            request_id=request.id,
            request_type=request.request_type,
            requested_by=request.requested_by,
            department=request.department,
            amount=request.amount,
            currency=request.currency,
            spend_tier=request.spend_tier,
            approval_chain=request.approval_chain or [],
            sla_deadline=request.sla_deadline,
        )
        event = build_event(TOPIC_APPROVAL_REQUESTED, self.service_name, payload)
        await self.publish(TOPIC_APPROVAL_REQUESTED, event)

    async def publish_approval_decided(
        self, request_id, decision, decided_by, decision_level,
        escalated, comments, decided_at=None
    ):
        """Publish an approval.decided event."""
        if decided_at is None:
            decided_at = datetime.now(timezone.utc)
        payload = build_approval_decided_payload(
            request_id=request_id,
            decision=decision,
            decided_by=decided_by,
            decision_level=decision_level,
            escalated=escalated,
            decided_at=decided_at,
            comments=comments,
        )
        event = build_event(TOPIC_APPROVAL_DECIDED, self.service_name, payload)
        await self.publish(TOPIC_APPROVAL_DECIDED, event)

    async def publish_license_usage_updated(self, license_data: dict):
        """Publish a license.usage.updated event.

        Args:
            license_data: dict with keys matching the event payload schema.
                          Anomaly fields (anomaly_score, top_factors, model_version)
                          are optional and default to 0.0 / [] / 'not_trained'.
        """
        payload = build_license_usage_updated_payload(
            license_id=license_data["license_id"],
            vendor_id=license_data["vendor_id"],
            app_name=license_data["app_name"],
            total_seats=license_data["total_seats"],
            active_seats_30d=license_data["active_seats_30d"],
            active_seats_60d=license_data["active_seats_60d"],
            active_seats_90d=license_data["active_seats_90d"],
            utilisation_score=license_data["utilisation_score"],
            period_end=license_data["period_end"],
            anomaly_score=license_data.get("anomaly_score", 0.0),
            top_factors=license_data.get("top_factors", []),
            model_version=license_data.get("model_version", "not_trained"),
        )
        event = build_event(TOPIC_LICENSE_USAGE_UPDATED, self.service_name, payload)
        await self.publish(TOPIC_LICENSE_USAGE_UPDATED, event)

    async def publish_notification(self, recipient, channel, template_name,
                                    template_context, priority, related_entity_id):
        """Publish a notification.send event (generic fallback)."""
        payload = {
            "recipient": recipient,
            "channel": channel,
            "template_name": template_name,
            "template_context": template_context,
            "priority": priority,
            "related_entity_id": related_entity_id,
        }
        event = build_event(TOPIC_NOTIFICATION_SEND, self.service_name, payload)
        await self.publish(TOPIC_NOTIFICATION_SEND, event)
