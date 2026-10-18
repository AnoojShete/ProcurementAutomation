"""Transactional outbox.

The problem it fixes: services used to commit a state change and then
publish its Kafka event as a separate step. A crash or broker outage in
between left the database changed and the event lost — nothing downstream
ever heard about it (e.g. requests stuck at `approved` with a signed
contract).

With the outbox, the event is written to `event_outbox` in the SAME
transaction as the state change, so both land or neither does. A relay
task (run_relay) then publishes unsent rows and marks them sent. Delivery
is at-least-once; consumers dedupe on event_id (see shared/eventing/inbox.py).

Usage at a call site — build a staged copy of the service's producer and
call its normal publish_* methods BEFORE committing:

    await staged(kafka_producer, db).publish_contract_signed(contract)
    await db.commit()
"""
import asyncio
import copy
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)

SCHEMA_SQL = [
    """
    CREATE TABLE IF NOT EXISTS event_outbox (
        id UUID PRIMARY KEY,
        source_service VARCHAR(64) NOT NULL,
        topic VARCHAR(128) NOT NULL,
        event_key TEXT,
        event_id VARCHAR(64),
        event JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        published_at TIMESTAMPTZ,
        attempts INTEGER NOT NULL DEFAULT 0,
        last_error TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_event_outbox_unsent ON event_outbox (source_service, created_at) WHERE published_at IS NULL",
    """
    CREATE TABLE IF NOT EXISTS event_inbox (
        consumer VARCHAR(64) NOT NULL,
        event_id VARCHAR(64) NOT NULL,
        topic VARCHAR(128) NOT NULL,
        processed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (consumer, event_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS event_dlq (
        id UUID PRIMARY KEY,
        consumer VARCHAR(64) NOT NULL,
        topic VARCHAR(128) NOT NULL,
        event_id VARCHAR(64),
        event JSONB NOT NULL,
        error TEXT NOT NULL,
        attempts INTEGER NOT NULL,
        failed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        status VARCHAR(20) NOT NULL DEFAULT 'open',
        resolved_at TIMESTAMPTZ,
        resolved_by VARCHAR(255),
        resolution TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_event_dlq_open ON event_dlq (consumer, failed_at) WHERE status = 'open'",
]


async def ensure_schema(engine) -> None:
    """Idempotent; every service that stages or consumes events calls it at
    startup. All services share one Postgres, so the tables are shared and
    rows are told apart by source_service / consumer."""
    async with engine.begin() as conn:
        for statement in SCHEMA_SQL:
            await conn.execute(text(statement))


async def enqueue(session, source_service: str, topic: str, event: dict, key: Optional[str] = None) -> str:
    """Adds the event to the caller's transaction. Does not commit."""
    row_id = str(uuid.uuid4())
    await session.execute(
        text(
            "INSERT INTO event_outbox (id, source_service, topic, event_key, event_id, event) "
            "VALUES (:id, :source, :topic, :key, :event_id, CAST(:event AS JSONB))"
        ),
        {
            "id": row_id, "source": source_service, "topic": topic, "key": key,
            "event_id": event.get("event_id"), "event": json.dumps(event, default=str),
        },
    )
    return row_id


def staged(producer, session):
    """A copy of `producer` whose publish() writes to the outbox inside
    `session` instead of sending. Every publish_* helper on the service
    producers funnels through self.publish, so they all work unchanged."""
    if producer is None:
        return None
    proxy = copy.copy(producer)

    async def _publish(topic: str, event: dict, key: Optional[str] = None):
        await enqueue(session, producer.service_name, topic, event, key)

    proxy.publish = _publish
    return proxy


SendFn = Callable[[str, dict, Optional[str]], Awaitable[None]]


async def relay_once(session_factory, source_service: str, send: SendFn, batch: int = 100) -> int:
    """Publishes one batch of unsent rows. FOR UPDATE SKIP LOCKED lets
    several processes of the same service relay side by side without
    sending a row twice. Returns how many rows were sent."""
    sent = 0
    async with session_factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT id, topic, event_key, event FROM event_outbox "
                    "WHERE source_service = :source AND published_at IS NULL "
                    "ORDER BY created_at LIMIT :batch FOR UPDATE SKIP LOCKED"
                ),
                {"source": source_service, "batch": batch},
            )
        ).all()
        for row in rows:
            event = row.event if isinstance(row.event, dict) else json.loads(row.event)
            try:
                await send(row.topic, event, row.event_key)
                await session.execute(
                    text("UPDATE event_outbox SET published_at = :now, attempts = attempts + 1, last_error = NULL WHERE id = :id"),
                    {"now": datetime.now(timezone.utc), "id": row.id},
                )
                sent += 1
            except Exception as e:
                await session.execute(
                    text("UPDATE event_outbox SET attempts = attempts + 1, last_error = :err WHERE id = :id"),
                    {"err": str(e)[:1000], "id": row.id},
                )
                # Keep order: stop this batch at the first failure (broker
                # likely down) and retry from here next round.
                break
        await session.commit()
    return sent


async def run_relay(session_factory, source_service: str, send: SendFn, interval_seconds: float = 0.5) -> None:
    """Background loop; cancel to stop."""
    logger.info(f"Outbox relay started for {source_service}")
    while True:
        try:
            sent = await relay_once(session_factory, source_service, send)
            if sent:
                logger.info(f"Outbox relay published {sent} event(s) for {source_service}")
                continue  # drain backlog without sleeping
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"Outbox relay error for {source_service}: {e}")
        await asyncio.sleep(interval_seconds)


def kafka_sender(aiokafka_producer) -> SendFn:
    """Adapter from an AIOKafkaProducer (value_serializer set to JSON) to
    the relay's send function."""
    async def _send(topic: str, event: dict, key: Optional[str]):
        await aiokafka_producer.send_and_wait(topic, event, key=key.encode("utf-8") if key else None)
    return _send


async def outbox_stats(session) -> dict:
    rows = (
        await session.execute(
            text(
                "SELECT source_service, count(*) FILTER (WHERE published_at IS NULL) AS pending, "
                "min(created_at) FILTER (WHERE published_at IS NULL) AS oldest_pending, "
                "count(*) FILTER (WHERE published_at > now() - interval '1 hour') AS sent_last_hour, "
                "max(last_error) FILTER (WHERE published_at IS NULL) AS last_error "
                "FROM event_outbox GROUP BY source_service ORDER BY source_service"
            )
        )
    ).all()
    return {
        r.source_service: {
            "pending": r.pending,
            "oldest_pending": r.oldest_pending.isoformat() if r.oldest_pending else None,
            "sent_last_hour": r.sent_last_hour,
            "last_error": r.last_error,
        }
        for r in rows
    }
