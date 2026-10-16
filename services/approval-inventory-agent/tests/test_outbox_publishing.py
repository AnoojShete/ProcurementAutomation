"""approval.decided starts contract generation, so it goes through the
transactional outbox with the decision: written in the same transaction,
never sent straight to Kafka after the commit (where an outage used to drop
it silently)."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.kafka.producer import KafkaEventProducer
from app.services.approval_service import ApprovalService


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _producer():
    producer = KafkaEventProducer.__new__(KafkaEventProducer)
    producer.service_name = "approval-inventory-agent"
    producer.producer = MagicMock(send_and_wait=AsyncMock(side_effect=ConnectionError("Kafka down")))
    return producer


def test_direct_decision_writes_approval_decided_to_the_outbox_before_commit():
    calls = []
    db = MagicMock()
    db.add = MagicMock()
    db.execute = AsyncMock(side_effect=lambda stmt, params=None: calls.append(("execute", str(stmt), params)))
    db.commit = AsyncMock(side_effect=lambda: calls.append(("commit",)))
    producer = _producer()
    req = SimpleNamespace(id="req-1", approval_chain=["manager"], current_approver_index=0, status="pending_approval")
    action = SimpleNamespace(decided_by="mgr@x", comments="ok")

    run(ApprovalService(db, producer, None)._process_decision_direct(req, "approved", action))

    outbox = [i for i, c in enumerate(calls) if c[0] == "execute" and "INSERT INTO event_outbox" in c[1]]
    commit = [i for i, c in enumerate(calls) if c[0] == "commit"]
    assert outbox and commit and outbox[0] < commit[0], calls
    assert calls[outbox[0]][2]["topic"] == "approval.decided"
    producer.producer.send_and_wait.assert_not_called()   # Kafka is the relay's job
    assert req.status == "approved"
