"""Kafka event producer for the Document & Vendor Intelligence Agent.

Publishes to the exact topic names in shared/kafka-topics.yaml, each
wrapped in the standard envelope from shared/schemas/events.md.
"""
import json
import logging
from aiokafka import AIOKafkaProducer
from app.kafka.events import (
    build_event,
    build_document_ingested_payload,
    build_document_classified_payload,
    build_vendor_matched_payload,
    build_vendor_payment_details_flagged_payload,
)

logger = logging.getLogger(__name__)

TOPIC_DOCUMENT_INGESTED = "document.ingested"
TOPIC_DOCUMENT_CLASSIFIED = "document.classified"
TOPIC_VENDOR_MATCHED = "vendor.matched"
TOPIC_VENDOR_PAYMENT_DETAILS_FLAGGED = "vendor.payment_details_flagged"


class KafkaEventProducer:
    def __init__(self, bootstrap_servers: str):
        self.producer = AIOKafkaProducer(
            bootstrap_servers=bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            acks="all",
        )
        self.service_name = "document-vendor-agent"

    async def start(self):
        await self.producer.start()
        logger.info("Kafka producer started")

    async def stop(self):
        await self.producer.stop()
        logger.info("Kafka producer stopped")

    async def publish(self, topic: str, event: dict):
        await self.producer.send_and_wait(topic, event)
        logger.info(f"Published event {event.get('event_type')} to {topic}")

    async def publish_document_ingested(self, document_id, uploaded_by, file_type, minio_path, uploaded_at):
        payload = build_document_ingested_payload(
            document_id=document_id, uploaded_by=uploaded_by, file_type=file_type,
            minio_path=minio_path, uploaded_at=uploaded_at,
        )
        event = build_event(TOPIC_DOCUMENT_INGESTED, self.service_name, payload)
        await self.publish(TOPIC_DOCUMENT_INGESTED, event)

    async def publish_document_classified(
        self, document_id, document_type, vendor_name_raw, extracted_fields,
        confidence_scores, overall_confidence, needs_review
    ):
        payload = build_document_classified_payload(
            document_id=document_id, document_type=document_type, vendor_name_raw=vendor_name_raw,
            extracted_fields=extracted_fields, confidence_scores=confidence_scores,
            overall_confidence=overall_confidence, needs_review=needs_review,
        )
        event = build_event(TOPIC_DOCUMENT_CLASSIFIED, self.service_name, payload)
        await self.publish(TOPIC_DOCUMENT_CLASSIFIED, event)

    async def publish_vendor_matched(self, document_id, vendor_id, vendor_name_normalized, match_type, match_confidence):
        payload = build_vendor_matched_payload(
            document_id=document_id, vendor_id=vendor_id, vendor_name_normalized=vendor_name_normalized,
            match_type=match_type, match_confidence=match_confidence,
        )
        event = build_event(TOPIC_VENDOR_MATCHED, self.service_name, payload)
        await self.publish(TOPIC_VENDOR_MATCHED, event)

    async def publish_vendor_payment_details_flagged(
        self, vendor_id, change_request_id, submitted_by, source, fields_changed, flagged_at
    ):
        payload = build_vendor_payment_details_flagged_payload(
            vendor_id=vendor_id, change_request_id=change_request_id, submitted_by=submitted_by,
            source=source, fields_changed=fields_changed, flagged_at=flagged_at,
        )
        event = build_event(TOPIC_VENDOR_PAYMENT_DETAILS_FLAGGED, self.service_name, payload)
        await self.publish(TOPIC_VENDOR_PAYMENT_DETAILS_FLAGGED, event)
