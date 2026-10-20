"""Live Kafka event log for the admin control panel.

A read-only tail of every topic in shared/kafka-topics.yaml. Each summary
is stored in the event_log table (FR-06: kept across restarts, searchable,
pruned after monitor.event_log_retention_days) and served by
GET /admin/control-panel/events. After a restart the tail resumes from the
last stored offset of each partition, so nothing is skipped.

It logs in as its own Kafka user, `event-monitor`
(EVENT_MONITOR_KAFKA_USERNAME / _PASSWORD), which may read every topic and
nothing else — it can't publish, and it uses no consumer group: partitions
are assigned directly and nothing is committed, so it never takes messages
away from the real consumers or shows up as lag.

Payloads are summarised, not passed through: only the allow-listed keys
below reach the browser. document.classified carries extracted fields
(including bank details), which never leave this process.
"""
import asyncio
import json
import logging
from collections import deque
import time
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

import yaml
from aiokafka import AIOKafkaConsumer, TopicPartition

from shared.kafka_security import kafka_auth_kwargs

logger = logging.getLogger(__name__)

TOPICS_FILE = Path(__file__).resolve().parents[2] / "shared" / "kafka-topics.yaml"

SAFE_KEYS = (
    "document_id", "vendor_id", "request_id", "purchase_request_id", "contract_id", "license_id",
    "change_request_id", "summary_id",
    "document_type", "file_type", "minio_path", "uploaded_by", "needs_review", "overall_confidence",
    "vendor_name_raw", "vendor_name_normalized", "match_type", "match_confidence",
    "request_type", "requested_by", "department", "amount", "currency", "spend_tier",
    "decision", "decided_by", "decision_level", "escalated",
    "template_used", "status", "signed_by", "esign_provider_ref",
    "risk_band", "risk_score", "alert_level", "days_remaining",
    "invoice_number", "po_number", "invoice_total",
    "recipient", "channel", "template_name", "priority", "related_entity_id",
    "rule_key", "changed_by", "source", "fields_changed",
    # reminder.due (FR-03)
    "kind", "entity_type", "entity_id", "threshold", "recipient_role", "waiting_hours", "notice_deadline",
)


def load_topics() -> list[str]:
    return list(yaml.safe_load(TOPICS_FILE.read_text())["topics"])


def _short(value) -> str:
    return str(value)[:8] if value else "?"


def describe(event_type: str, p: dict) -> str:
    """One line a person can read in the log."""
    match event_type:
        case "document.ingested":
            return f"Document {_short(p.get('document_id'))} received from {p.get('uploaded_by')} -> stored at {p.get('minio_path')}"
        case "document.classified":
            review = " (needs review)" if p.get("needs_review") else ""
            return f"Document {_short(p.get('document_id'))} classified as {p.get('document_type')}{review}"
        case "vendor.matched":
            return f"Vendor {p.get('vendor_name_normalized')} matched ({p.get('match_type')})"
        case "approval.requested":
            return f"Purchase request {_short(p.get('request_id'))} for {p.get('amount')} {p.get('currency') or ''} -> tier {p.get('spend_tier')}"
        case "approval.decided":
            return f"Request {_short(p.get('request_id'))} {p.get('decision')} by {p.get('decided_by')}"
        case "contract.generated":
            return f"Contract {_short(p.get('contract_id'))} generated for request {_short(p.get('purchase_request_id'))}"
        case "contract.signed":
            return f"Contract {_short(p.get('contract_id'))} signed by {p.get('signed_by')}"
        case "notification.send":
            return f"Notify {p.get('recipient')}: {p.get('template_name')} via {p.get('channel')}"
        case "invoice.matched":
            return f"Invoice {p.get('invoice_number')} matched to PO {p.get('po_number')}"
        case "risk.score.updated":
            return f"Vendor {_short(p.get('vendor_id'))} risk {p.get('risk_band')}"
        case "reminder.due":
            return (f"Reminder: {str(p.get('kind', '')).replace('_', ' ')} on {p.get('entity_type')} "
                    f"{_short(p.get('entity_id'))} ({p.get('threshold')}, waiting {p.get('waiting_hours')}h)")
        case "contract.renewal.due":
            return (f"Contract {_short(p.get('contract_id'))} renewal: {p.get('alert_level')} days before "
                    f"notice deadline {p.get('notice_deadline') or '?'}")
        case "contract.obligation.due":
            return (f"Contract {_short(p.get('contract_id'))} obligation {p.get('label')}: {p.get('kind')}"
                    f" ({p.get('detail')})")
        case "budget.threshold_crossed":
            return (f"Budget {p.get('department')} {p.get('category')} {p.get('period')} {p.get('fiscal_year')} "
                    f"{p.get('status')}: {p.get('left_inr')} INR left after request {_short(p.get('request_id'))}")
        case "rfq.issued":
            return (f"{p.get('reference')} round {p.get('round')} issued to {len(p.get('vendor_ids') or [])} vendors, "
                    f"deadline {p.get('deadline')}")
        case "rfq.awarded":
            return f"{p.get('reference')} awarded to vendor {_short(p.get('vendor_id'))}: {p.get('total_inr')} INR"
        case "goods.received":
            return (f"Request {_short(p.get('request_id'))}: delivery recorded"
                    f" ({'complete' if p.get('complete') else 'partial'})")
    return event_type


def summarize(topic: str, partition: int, offset: int, timestamp_ms: int | None, raw: bytes | None) -> dict:
    try:
        event = json.loads(raw or b"{}")
    except (ValueError, UnicodeDecodeError):
        event = {}
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    when = event.get("timestamp")
    if not when and timestamp_ms:
        when = datetime.fromtimestamp(timestamp_ms / 1000, timezone.utc).isoformat()
    event_type = event.get("event_type") or topic
    return {
        "topic": topic,
        "partition": partition,
        "offset": offset,
        "timestamp": when,
        "event_type": event_type,
        "source_service": event.get("source_service"),
        "correlation_id": event.get("correlation_id"),
        "message": describe(event_type, payload),
        "fields": {k: payload[k] for k in SAFE_KEYS if payload.get(k) not in (None, "", [])},
    }


_INSERT = text("""
    INSERT INTO event_log (topic, kafka_partition, kafka_offset, event_time, event_type, source_service,
                           correlation_id, message, fields)
    VALUES (:topic, :partition, :offset, :timestamp, :event_type, :source_service,
            :correlation_id, :message, CAST(:fields AS jsonb))
    ON CONFLICT (topic, kafka_partition, kafka_offset) DO NOTHING
""")
PRUNE_EVERY_SECONDS = 3600


def _parse_time(value) -> datetime | None:
    if not value:
        return None
    try:
        t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def retention_days() -> int:
    from shared.rules_engine import get_rule
    days = get_rule("monitor.event_log_retention_days", fallback=14)
    return days if isinstance(days, int) and days > 0 else 14


def start_offset(last_stored: int | None, begin: int, end: int, backlog: int, first_connect: bool) -> int:
    """Where to start reading a partition. Already stored: right after the
    last stored record, so a restart skips nothing. Never seen: the recent
    `backlog`, so the log isn't empty. Reconnect without storage: the end."""
    if last_stored is not None:
        return max(begin, last_stored + 1)
    if first_connect:
        return max(begin, end - backlog)
    return end


def build_query(after: int, limit: int, topic: str | None, correlation_id: str | None,
                since_hours: float | None, q: str | None):
    """SQL and params for the filtered log, newest `limit` rows after `after`."""
    where, params = ["id > :after"], {"after": after, "limit": limit}
    if topic:
        where.append("topic = :topic"); params["topic"] = topic
    if correlation_id:
        where.append("correlation_id = :cid"); params["cid"] = correlation_id
    if since_hours:
        where.append("event_time >= now() - make_interval(secs => :secs)"); params["secs"] = since_hours * 3600
    if q:
        where.append("(message ILIKE :q OR fields::text ILIKE :q)"); params["q"] = f"%{q}%"
    sql = text(
        "SELECT id AS seq, topic, kafka_partition AS partition, kafka_offset AS offset, event_time, event_type, "
        "source_service, correlation_id, message, fields FROM event_log "
        f"WHERE {' AND '.join(where)} ORDER BY id DESC LIMIT :limit"
    )
    return sql, params


class EventMonitor:
    def __init__(self, bootstrap_servers: str, backlog_per_partition: int = 50, maxlen: int = 500,
                 session_factory=None):
        self.bootstrap_servers = bootstrap_servers
        self.backlog = backlog_per_partition
        self.events: deque[dict] = deque(maxlen=maxlen)
        self.seq = 0
        self.connected = False
        self.error: str | None = None
        self.topics: list[str] = []
        # With a session factory the log lives in event_log (survives restarts).
        self.session_factory = session_factory
        self._last_prune = 0.0

    async def store(self, entries: list[dict]) -> None:
        if not self.session_factory or not entries:
            return
        async with self.session_factory() as session:
            await session.execute(_INSERT, [{**e, "timestamp": _parse_time(e.get("timestamp")),
                                             "fields": json.dumps(e["fields"])} for e in entries])
            await session.commit()

    async def stored_offsets(self) -> dict:
        """(topic, partition) -> last stored offset, to resume after a restart."""
        if not self.session_factory:
            return {}
        async with self.session_factory() as session:
            rows = (await session.execute(text(
                "SELECT topic, kafka_partition, max(kafka_offset) AS last FROM event_log GROUP BY 1, 2"
            ))).all()
        return {(r.topic, r.kafka_partition): r.last for r in rows}

    async def query(self, after: int = 0, limit: int = 200, topic: str | None = None,
                    correlation_id: str | None = None, since_hours: float | None = None,
                    q: str | None = None) -> tuple[list[dict], int]:
        if not self.session_factory:
            return self.since(after, limit), self.seq
        sql, params = build_query(after, limit, topic, correlation_id, since_hours, q)
        async with self.session_factory() as session:
            rows = (await session.execute(sql, params)).mappings().all()
            latest = (await session.execute(text("SELECT coalesce(max(id), 0) FROM event_log"))).scalar()
        events = [{**dict(r), "timestamp": r["event_time"].isoformat() if r["event_time"] else None} for r in rows]
        for e in events:
            e.pop("event_time", None)
        return list(reversed(events)), int(latest)

    async def prune(self) -> int:
        if not self.session_factory:
            return 0
        async with self.session_factory() as session:
            result = await session.execute(text(
                "DELETE FROM event_log WHERE stored_at < now() - make_interval(days => :d)"
            ), {"d": retention_days()})
            await session.commit()
        return result.rowcount or 0

    def add(self, entry: dict) -> None:
        self.seq += 1
        self.events.append({"seq": self.seq, **entry})

    def since(self, after: int, limit: int) -> list[dict]:
        newer = [e for e in self.events if e["seq"] > after]
        return newer[-limit:]

    def status(self) -> dict:
        return {"connected": self.connected, "error": self.error, "topics": self.topics, "buffered": len(self.events)}

    async def _tail_once(self) -> None:
        consumer = AIOKafkaConsumer(
            bootstrap_servers=self.bootstrap_servers,
            group_id=None,
            enable_auto_commit=False,
            **kafka_auth_kwargs("EVENT_MONITOR_KAFKA"),
        )
        await consumer.start()
        try:
            wanted = set(load_topics())
            available = await consumer.topics()  # fetches metadata for the topics we may read
            self.topics = sorted(wanted & available)
            tps = [
                TopicPartition(t, p) for t in self.topics for p in sorted(consumer.partitions_for_topic(t) or [])
            ]
            consumer.assign(tps)
            stored = await self.stored_offsets()
            begin = await consumer.beginning_offsets(tps)
            end = await consumer.end_offsets(tps)
            for tp in tps:
                consumer.seek(tp, start_offset(stored.get((tp.topic, tp.partition)), begin[tp], end[tp],
                                               self.backlog, first_connect=not self.events))
            self.connected, self.error = True, None
            logger.info(f"[event-monitor] tailing {len(self.topics)} topics")
            while True:
                batches = await consumer.getmany(timeout_ms=1000, max_records=500)
                records = [r for rs in batches.values() for r in rs]
                entries = [summarize(r.topic, r.partition, r.offset, r.timestamp, r.value)
                           for r in sorted(records, key=lambda r: r.timestamp or 0)]
                for e in entries:
                    self.add(e)
                await self.store(entries)
                if self.session_factory and time.monotonic() - self._last_prune > PRUNE_EVERY_SECONDS:
                    self._last_prune = time.monotonic()
                    pruned = await self.prune()
                    if pruned:
                        logger.info(f"[event-monitor] pruned {pruned} events older than the retention window")
        finally:
            self.connected = False
            await consumer.stop()

    async def run(self) -> None:
        while True:
            try:
                await self._tail_once()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.connected, self.error = False, f"{type(e).__name__}: {e}"
                logger.warning(f"[event-monitor] Kafka tail stopped ({self.error}); reconnecting in 5s")
                await asyncio.sleep(5)
