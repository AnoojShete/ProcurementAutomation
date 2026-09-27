"""Consumer side: dedupe, retry, dead-letter.

Before this, every consumer loop caught handler exceptions, logged them
and moved on — with offsets auto-committed, a failed event was simply
gone. deliver() instead:

  1. skips an event this consumer already processed (event_inbox);
  2. retries the handler with backoff;
  3. on final failure writes the full event + error to event_dlq, where an
     operator can see it and replay it (replay_dlq_entry) once the cause is
     fixed.

Marking the inbox happens after the handler commits, so a crash in between
can redeliver once; handlers are therefore written to be idempotent (the
purchase-request state machine turns a repeated transition into a no-op).
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)

DEFAULT_BACKOFF_SECONDS = (0.5, 2.0, 5.0)


class PermanentEventError(Exception):
    """Raised by a handler for an event that can never succeed (bad
    payload, unknown entity). Skips the remaining retries and goes straight
    to the DLQ."""


async def already_processed(session_factory, consumer: str, event_id: Optional[str]) -> bool:
    if not event_id:
        return False
    async with session_factory() as session:
        row = (
            await session.execute(
                text("SELECT 1 FROM event_inbox WHERE consumer = :c AND event_id = :e"),
                {"c": consumer, "e": event_id},
            )
        ).first()
    return row is not None


async def mark_processed(session_factory, consumer: str, event_id: Optional[str], topic: str) -> None:
    if not event_id:
        return
    async with session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO event_inbox (consumer, event_id, topic) VALUES (:c, :e, :t) "
                "ON CONFLICT (consumer, event_id) DO NOTHING"
            ),
            {"c": consumer, "e": event_id, "t": topic},
        )
        await session.commit()


async def dead_letter(session_factory, consumer: str, topic: str, event: dict, error: str, attempts: int) -> str:
    dlq_id = str(uuid.uuid4())
    async with session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO event_dlq (id, consumer, topic, event_id, event, error, attempts) "
                "VALUES (:id, :c, :t, :e, CAST(:ev AS JSONB), :err, :a)"
            ),
            {
                "id": dlq_id, "c": consumer, "t": topic, "e": event.get("event_id"),
                "ev": json.dumps(event, default=str), "err": error[:4000], "a": attempts,
            },
        )
        await session.commit()
    return dlq_id


async def deliver(
    session_factory,
    consumer: str,
    topic: str,
    event: dict,
    handler: Callable[[], Awaitable[None]],
    backoff: tuple = DEFAULT_BACKOFF_SECONDS,
) -> str:
    """Runs `handler` for one event. Returns "skipped" | "processed" |
    "dead_lettered". Never raises (except cancellation), so one bad event
    can't stop the consumer loop."""
    event_id = event.get("event_id")
    if await already_processed(session_factory, consumer, event_id):
        logger.info(f"[{consumer}] skipping already-processed event {event_id} on {topic}")
        return "skipped"

    attempts = 0
    last_error = ""
    for delay in (0.0, *backoff):
        if delay:
            await asyncio.sleep(delay)
        attempts += 1
        try:
            await handler()
            await mark_processed(session_factory, consumer, event_id, topic)
            return "processed"
        except asyncio.CancelledError:
            raise
        except PermanentEventError as e:
            last_error = f"{type(e).__name__}: {e}"
            break
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
            logger.warning(f"[{consumer}] {topic} event {event_id} attempt {attempts} failed: {last_error}")

    dlq_id = await dead_letter(session_factory, consumer, topic, event, last_error, attempts)
    logger.error(f"[{consumer}] {topic} event {event_id} dead-lettered as {dlq_id} after {attempts} attempt(s): {last_error}")
    return "dead_lettered"


async def list_dlq(session, consumer: Optional[str] = None, status: str = "open", limit: int = 100) -> list[dict]:
    where = ["status = :status"]
    params: dict = {"status": status, "limit": limit}
    if consumer:
        where.append("consumer = :consumer")
        params["consumer"] = consumer
    rows = (
        await session.execute(
            text(
                "SELECT id, consumer, topic, event_id, event, error, attempts, failed_at, status, "
                "resolved_at, resolved_by, resolution FROM event_dlq "
                f"WHERE {' AND '.join(where)} ORDER BY failed_at DESC LIMIT :limit"
            ),
            params,
        )
    ).all()
    return [
        {
            "id": str(r.id), "consumer": r.consumer, "topic": r.topic, "event_id": r.event_id,
            "event": r.event, "error": r.error, "attempts": r.attempts,
            "failed_at": r.failed_at.isoformat(), "status": r.status,
            "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
            "resolved_by": r.resolved_by, "resolution": r.resolution,
        }
        for r in rows
    ]


async def get_dlq_entry(session, dlq_id: str) -> Optional[dict]:
    row = (
        await session.execute(
            text("SELECT id, consumer, topic, event, status FROM event_dlq WHERE id = :id"), {"id": dlq_id}
        )
    ).first()
    if row is None:
        return None
    event = row.event if isinstance(row.event, dict) else json.loads(row.event)
    return {"id": str(row.id), "consumer": row.consumer, "topic": row.topic, "event": event, "status": row.status}


async def resolve_dlq_entry(session_factory, dlq_id: str, status: str, by: str, resolution: str) -> None:
    async with session_factory() as session:
        await session.execute(
            text(
                "UPDATE event_dlq SET status = :s, resolved_at = :now, resolved_by = :by, resolution = :r "
                "WHERE id = :id"
            ),
            {"s": status, "now": datetime.now(timezone.utc), "by": by, "r": resolution[:2000], "id": dlq_id},
        )
        await session.commit()


async def replay_dlq_entry(
    session_factory, dlq_id: str, consumer: str, dispatch: Callable[[str, dict], Awaitable[None]], replayed_by: str,
) -> dict:
    """Runs the event through this consumer's handler again, directly —
    not by re-publishing, which would also redeliver it to every other
    consumer group on the topic. Returns {"status": "replayed"|"failed", ...}."""
    async with session_factory() as session:
        entry = await get_dlq_entry(session, dlq_id)
    if entry is None or entry["consumer"] != consumer:
        raise LookupError(f"DLQ entry {dlq_id} not found for {consumer}")
    if entry["status"] != "open":
        raise ValueError(f"DLQ entry {dlq_id} is already {entry['status']}")
    try:
        await dispatch(entry["topic"], entry["event"])
    except Exception as e:
        return {"status": "failed", "error": f"{type(e).__name__}: {e}"}
    await mark_processed(session_factory, consumer, entry["event"].get("event_id"), entry["topic"])
    await resolve_dlq_entry(session_factory, dlq_id, "replayed", replayed_by, "replayed successfully")
    return {"status": "replayed"}


async def dlq_counts(session) -> dict:
    rows = (
        await session.execute(
            text("SELECT consumer, status, count(*) AS n FROM event_dlq GROUP BY consumer, status")
        )
    ).all()
    out: dict = {}
    for r in rows:
        out.setdefault(r.consumer, {})[r.status] = r.n
    return out
