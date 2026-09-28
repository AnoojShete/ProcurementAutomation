"""Kafka consumer for the Document & Vendor Intelligence Agent's background
worker (app/worker.py). Consumes document.ingested — published by this
same service's POST /documents/upload and /documents/upload/batch — and
runs the extraction pipeline.

Documents are processed concurrently: up to settings.worker_concurrency
at a time per worker process, and document.ingested is created with
settings.document_ingested_partitions partitions so extra worker replicas
share the load. Before this, the loop awaited each document in turn, so a
batch of uploads queued behind whichever file was slowest to OCR.
"""
import json
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiokafka import AIOKafkaConsumer
from aiokafka.admin import AIOKafkaAdminClient, NewPartitions, NewTopic
from shared.kafka_security import kafka_auth_kwargs
from sqlalchemy import select, update

from app.config import settings
from app.database import async_session_factory
from app.models import Document
from app.services.document_service import process_document

from shared.infra.retry import with_retry
from shared.logging.context import CorrelationContext

logger = logging.getLogger(__name__)

TOPIC_DOCUMENT_INGESTED = "document.ingested"

CONSUME_TOPICS = [
    TOPIC_DOCUMENT_INGESTED,  # published by this service's own API process
    "business_rule.updated",  # published by auth-service
]

# A document still "pending" this long after its last change missed its
# event (worker down when it was published) or is waiting for a retry; one
# still "processing" this long belongs to a worker that died mid-pipeline
# (extraction itself is time-limited, see ocr.extract_text_isolated).
STALE_PENDING_AFTER = timedelta(minutes=1)
STALE_PROCESSING_AFTER = timedelta(minutes=5)
MAX_ATTEMPTS = 5
SWEEP_INTERVAL_SECONDS = 60
GAVE_UP_MESSAGE = (
    "We couldn't finish processing this document after several attempts because of a problem on our side. "
    "Please upload it again later; if it keeps failing, contact support."
)


async def ensure_ingest_partitions(bootstrap_servers: str, partitions: int) -> None:
    """Create document.ingested with `partitions` partitions, or grow it if
    Redpanda auto-created it with fewer. Never shrinks (Kafka can't)."""
    admin = AIOKafkaAdminClient(bootstrap_servers=bootstrap_servers, **kafka_auth_kwargs())
    await admin.start()
    try:
        existing = await admin.list_topics()
        if TOPIC_DOCUMENT_INGESTED not in existing:
            await admin.create_topics(
                [NewTopic(TOPIC_DOCUMENT_INGESTED, num_partitions=partitions, replication_factor=1)]
            )
            logger.info(f"Created {TOPIC_DOCUMENT_INGESTED} with {partitions} partitions")
            return
        described = await admin.describe_topics([TOPIC_DOCUMENT_INGESTED])
        current = len(described[0]["partitions"]) if described else 0
        if 0 < current < partitions:
            await admin.create_partitions({TOPIC_DOCUMENT_INGESTED: NewPartitions(total_count=partitions)})
            logger.info(f"Grew {TOPIC_DOCUMENT_INGESTED} from {current} to {partitions} partitions")
    finally:
        await admin.close()


async def claim_document(db, document_id: str) -> bool:
    """Atomically move a document pending -> processing. Returns False if
    another worker (or an earlier delivery of the same event) already
    claimed it, so a redelivered event never runs the pipeline twice."""
    result = await db.execute(
        update(Document)
        .where(Document.id == document_id, Document.status == "pending")
        .values(status="processing", updated_at=datetime.now(timezone.utc),
                processing_attempts=Document.processing_attempts + 1)
    )
    await db.commit()
    return result.rowcount == 1


async def requeue_stranded_documents(kafka_producer) -> int:
    """Re-publish document.ingested for documents that never got processed.
    Safe with several workers starting at once: claim_document() lets only
    one of them run each document."""
    now = datetime.now(timezone.utc)
    async with async_session_factory() as db:
        # Out of attempts (a poison file that keeps killing the worker, or a
        # persistent outage): stop, and tell the uploader.
        gave_up = await db.execute(
            update(Document)
            .where(Document.status.in_(("pending", "processing")),
                   Document.processing_attempts >= MAX_ATTEMPTS,
                   Document.updated_at < now - STALE_PENDING_AFTER)
            .values(status="failed", error_message=GAVE_UP_MESSAGE, updated_at=now)
        )
        # A dead worker's in-flight documents go back to pending.
        await db.execute(
            update(Document)
            .where(Document.status == "processing", Document.updated_at < now - STALE_PROCESSING_AFTER)
            .values(status="pending", updated_at=now)
        )
        await db.commit()
        if gave_up.rowcount:
            logger.warning(f"Gave up on {gave_up.rowcount} document(s) after {MAX_ATTEMPTS} attempts")
        candidates = (
            await db.execute(
                select(Document).where(
                    Document.status == "pending", Document.updated_at < now - STALE_PENDING_AFTER
                )
            )
        ).scalars().all()
    # Back off between retries: wait 1 min after the 1st attempt, 2 after
    # the 2nd... so a short outage of a service the pipeline needs is
    # ridden out (about 10 minutes in total) before giving up.
    stranded = [d for d in candidates
                if d.updated_at < now - STALE_PENDING_AFTER * max(1, d.processing_attempts or 0)]
    for doc in stranded:
        await kafka_producer.publish_document_ingested(
            document_id=doc.id, uploaded_by=doc.uploaded_by, file_type=doc.file_type,
            minio_path=doc.minio_path, uploaded_at=doc.uploaded_at,
        )
    if stranded:
        logger.info(f"Re-queued {len(stranded)} stranded document(s)")
    return len(stranded)


async def start_consumer(kafka_producer):
    try:
        await with_retry(
            lambda: ensure_ingest_partitions(settings.kafka_bootstrap_servers, settings.document_ingested_partitions),
            name="Kafka topic setup",
        )
    except Exception as e:
        # Not fatal: an auto-created single-partition topic still works,
        # it just can't be shared between worker replicas.
        logger.warning(f"Could not set {TOPIC_DOCUMENT_INGESTED} partitions: {e}")

    consumer = AIOKafkaConsumer(
        *CONSUME_TOPICS,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.kafka_consumer_group,
        auto_offset_reset="earliest",
        session_timeout_ms=60000,
        heartbeat_interval_ms=10000,
        max_poll_interval_ms=600000,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        **kafka_auth_kwargs(),
    )

    slots = asyncio.Semaphore(max(1, settings.worker_concurrency))
    in_flight: set[asyncio.Task] = set()

    try:
        await with_retry(consumer.start, name="Kafka consumer")
        logger.info(
            f"Kafka consumer started, listening on: {CONSUME_TOPICS} "
            f"(concurrency={settings.worker_concurrency})"
        )
        # Not just at startup: a document can be stranded or waiting for a
        # retry at any time.
        sweep_task = asyncio.create_task(_sweep_forever(kafka_producer))

        async for msg in consumer:
            try:
                event = msg.value
                correlation_id = event.get("correlation_id")
                event_type = event.get("event_type")
                payload = event.get("payload", {})

                if event_type == "document.ingested":
                    # Wait for a free slot before pulling the next message,
                    # so a burst of uploads is worked through N at a time
                    # instead of piling up unbounded tasks.
                    await slots.acquire()
                    task = asyncio.create_task(
                        _run_document(kafka_producer, payload, correlation_id, slots)
                    )
                    in_flight.add(task)
                    task.add_done_callback(in_flight.discard)
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
        if "sweep_task" in locals():
            sweep_task.cancel()
        if in_flight:
            logger.info(f"Waiting for {len(in_flight)} in-flight document(s) to finish")
            await asyncio.gather(*in_flight, return_exceptions=True)
        await consumer.stop()
        logger.info("Kafka consumer stopped")


async def _sweep_forever(kafka_producer):
    while True:
        try:
            await requeue_stranded_documents(kafka_producer)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"Stranded-document sweep failed: {e}", exc_info=True)
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)


async def _run_document(kafka_producer, payload: dict, correlation_id: str | None, slots: asyncio.Semaphore):
    # Each task runs in its own context copy, so setting the correlation id
    # here doesn't leak into documents being processed alongside it.
    try:
        if correlation_id:
            CorrelationContext.set(correlation_id)
        await _handle_document_ingested(kafka_producer, payload)
    except Exception as e:
        logger.error(f"Document pipeline task failed: {e}", exc_info=True)
    finally:
        slots.release()


async def _handle_document_ingested(kafka_producer, payload: dict):
    document_id = payload.get("document_id")
    async with async_session_factory() as db:
        if not await claim_document(db, document_id):
            logger.info(f"document.ingested skipped, already claimed or not pending: document_id={document_id}")
            return
        logger.info(f"document.ingested received, running extraction pipeline: document_id={document_id}")
        await process_document(db, kafka_producer, document_id)
