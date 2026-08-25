"""Kafka event producer for the Contract & Risk Analysis Agent.

Publishes to the exact topic names in shared/kafka-topics.yaml, each
wrapped in the standard envelope from shared/schemas/events.md.
"""
import json
import logging
from aiokafka import AIOKafkaProducer
from app.kafka.events import (
    build_event,
    build_contract_generated_payload,
    build_contract_signed_payload,
    build_contract_renewal_due_payload,
    build_risk_score_updated_payload,
    build_vendor_offboarded_payload,
    build_notification_send_payload,
)

logger = logging.getLogger(__name__)

TOPIC_CONTRACT_GENERATED = "contract.generated"
TOPIC_CONTRACT_SIGNED = "contract.signed"
TOPIC_CONTRACT_RENEWAL_DUE = "contract.renewal.due"
TOPIC_RISK_SCORE_UPDATED = "risk.score.updated"
TOPIC_VENDOR_OFFBOARDED = "vendor.offboarded"
TOPIC_NOTIFICATION_SEND = "notification.send"


class KafkaEventProducer:
    def __init__(self, bootstrap_servers: str):
        self.producer = AIOKafkaProducer(
            bootstrap_servers=bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            acks="all",
        )
        self.service_name = "contract-risk-agent"

    async def start(self):
        await self.producer.start()
        logger.info("Kafka producer started")

    async def stop(self):
        await self.producer.stop()
        logger.info("Kafka producer stopped")

    async def publish(self, topic: str, event: dict):
        await self.producer.send_and_wait(topic, event)
        logger.info(f"Published event {event.get('event_type')} to {topic}")

    async def publish_contract_generated(self, contract):
        payload = build_contract_generated_payload(
            contract_id=contract.id,
            purchase_request_id=contract.purchase_request_id,
            vendor_id=contract.vendor_id,
            template_used=contract.template,
            version=contract.version,
            status=contract.status,
            generated_at=contract.generated_at,
        )
        event = build_event(TOPIC_CONTRACT_GENERATED, self.service_name, payload)
        await self.publish(TOPIC_CONTRACT_GENERATED, event)

    async def publish_contract_signed(self, contract):
        payload = build_contract_signed_payload(
            contract_id=contract.id,
            signed_at=contract.signed_at,
            signed_by=contract.signed_by,
            esign_provider_ref=contract.esign_provider_ref,
        )
        event = build_event(TOPIC_CONTRACT_SIGNED, self.service_name, payload)
        await self.publish(TOPIC_CONTRACT_SIGNED, event)

    async def publish_contract_renewal_due(
        self, contract_id, vendor_id, renewal_type, notice_period_days,
        contract_end_date, days_remaining, alert_level
    ):
        payload = build_contract_renewal_due_payload(
            contract_id=contract_id,
            vendor_id=vendor_id,
            renewal_type=renewal_type,
            notice_period_days=notice_period_days,
            contract_end_date=contract_end_date,
            days_remaining=days_remaining,
            alert_level=alert_level,
        )
        event = build_event(TOPIC_CONTRACT_RENEWAL_DUE, self.service_name, payload)
        await self.publish(TOPIC_CONTRACT_RENEWAL_DUE, event)

    async def publish_risk_score_updated(
        self, vendor_id, risk_band, risk_score, top_factors, model_version, scored_at
    ):
        payload = build_risk_score_updated_payload(
            vendor_id=vendor_id,
            risk_band=risk_band,
            risk_score=risk_score,
            top_factors=top_factors,
            model_version=model_version,
            scored_at=scored_at,
        )
        event = build_event(TOPIC_RISK_SCORE_UPDATED, self.service_name, payload)
        await self.publish(TOPIC_RISK_SCORE_UPDATED, event)

    async def publish_vendor_offboarded(
        self, vendor_id, offboarded_by, offboarded_at, contracts_flagged, data_retention_flag
    ):
        payload = build_vendor_offboarded_payload(
            vendor_id=vendor_id,
            offboarded_by=offboarded_by,
            offboarded_at=offboarded_at,
            contracts_flagged=contracts_flagged,
            data_retention_flag=data_retention_flag,
        )
        event = build_event(TOPIC_VENDOR_OFFBOARDED, self.service_name, payload)
        await self.publish(TOPIC_VENDOR_OFFBOARDED, event)

    async def publish_notification(
        self, recipient, channel, template_name, template_context, priority, related_entity_id
    ):
        payload = build_notification_send_payload(
            recipient=recipient,
            channel=channel,
            template_name=template_name,
            template_context=template_context,
            priority=priority,
            related_entity_id=related_entity_id,
        )
        event = build_event(TOPIC_NOTIFICATION_SEND, self.service_name, payload)
        await self.publish(TOPIC_NOTIFICATION_SEND, event)
