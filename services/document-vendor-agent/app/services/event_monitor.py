"""Live Kafka event log for the admin control panel.

A read-only tail of every topic in shared/kafka-topics.yaml, kept in memory
(the last `maxlen` events) and served by GET /admin/control-panel/events.

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
from datetime import datetime, timezone
from pathlib import Path

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


class EventMonitor:
    def __init__(self, bootstrap_servers: str, backlog_per_partition: int = 50, maxlen: int = 500):
        self.bootstrap_servers = bootstrap_servers
        self.backlog = backlog_per_partition
        self.events: deque[dict] = deque(maxlen=maxlen)
        self.seq = 0
        self.connected = False
        self.error: str | None = None
        self.topics: list[str] = []

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
            if not self.events:
                # First connect: show the recent history, not an empty log.
                begin = await consumer.beginning_offsets(tps)
                end = await consumer.end_offsets(tps)
                for tp in tps:
                    consumer.seek(tp, max(begin[tp], end[tp] - self.backlog))
            else:
                await consumer.seek_to_end(*tps)
            self.connected, self.error = True, None
            logger.info(f"[event-monitor] tailing {len(self.topics)} topics")
            while True:
                batches = await consumer.getmany(timeout_ms=1000, max_records=500)
                records = [r for rs in batches.values() for r in rs]
                for r in sorted(records, key=lambda r: r.timestamp or 0):
                    self.add(summarize(r.topic, r.partition, r.offset, r.timestamp, r.value))
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
