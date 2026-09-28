"""shared/eventing — outbox staging/relay and consumer retry/dead-letter."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from shared.eventing import inbox, outbox


class _Producer:
    service_name = "test-service"

    def __init__(self):
        self.sent = []

    async def publish(self, topic, event, key=None):
        self.sent.append((topic, event))

    async def publish_thing(self, thing_id):
        await self.publish("thing.happened", {"event_id": f"e-{thing_id}", "payload": {"id": thing_id}})


@pytest.mark.asyncio
async def test_staged_producer_writes_to_outbox_not_kafka():
    producer = _Producer()
    session = AsyncMock()
    await outbox.staged(producer, session).publish_thing("42")

    assert producer.sent == []  # nothing went straight to Kafka
    sql, params = session.execute.call_args.args
    assert "INSERT INTO event_outbox" in str(sql)
    assert params["topic"] == "thing.happened"
    assert params["source"] == "test-service"
    assert json.loads(params["event"])["payload"] == {"id": "42"}
    session.commit.assert_not_called()  # the caller's transaction decides


def test_staged_none_is_none():
    assert outbox.staged(None, AsyncMock()) is None


class _FakeSession:
    def __init__(self, rows):
        self.rows = rows
        self.updates = []
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, sql, params=None):
        q = str(sql)
        if q.startswith("SELECT"):
            res = MagicMock()
            res.all.return_value = self.rows
            return res
        self.updates.append((q, params))
        return MagicMock()

    async def commit(self):
        self.committed = True


@pytest.mark.asyncio
async def test_relay_marks_sent_and_stops_at_first_failure():
    rows = [
        SimpleNamespace(id="r1", topic="t", event_key="k1", event={"event_id": "1"}),
        SimpleNamespace(id="r2", topic="t", event_key=None, event={"event_id": "2"}),
        SimpleNamespace(id="r3", topic="t", event_key=None, event={"event_id": "3"}),
    ]
    session = _FakeSession(rows)
    calls = []

    async def send(topic, event, key):
        calls.append(event["event_id"])
        if event["event_id"] == "2":
            raise ConnectionError("broker down")

    sent = await outbox.relay_once(lambda: session, "svc", send)

    assert sent == 1
    assert calls == ["1", "2"]  # r3 waits for the next round, preserving order
    assert "published_at" in session.updates[0][0] and session.updates[0][1]["id"] == "r1"
    assert "last_error" in session.updates[1][0] and "broker down" in session.updates[1][1]["err"]
    assert session.committed


@pytest.fixture
def no_db(monkeypatch):
    state = {"processed": set(), "dlq": []}

    async def already(_sf, consumer, event_id):
        return (consumer, event_id) in state["processed"]

    async def mark(_sf, consumer, event_id, topic):
        state["processed"].add((consumer, event_id))

    async def dead(_sf, consumer, topic, event, error, attempts):
        state["dlq"].append({"event": event, "error": error, "attempts": attempts})
        return "dlq-1"

    monkeypatch.setattr(inbox, "already_processed", already)
    monkeypatch.setattr(inbox, "mark_processed", mark)
    monkeypatch.setattr(inbox, "dead_letter", dead)
    return state


@pytest.mark.asyncio
async def test_deliver_retries_then_succeeds(no_db):
    handler = AsyncMock(side_effect=[RuntimeError("db blip"), None])
    out = await inbox.deliver(None, "c", "t", {"event_id": "e1"}, handler, backoff=(0, 0))
    assert out == "processed"
    assert handler.await_count == 2
    assert ("c", "e1") in no_db["processed"]


@pytest.mark.asyncio
async def test_deliver_dead_letters_after_retries_instead_of_dropping(no_db):
    handler = AsyncMock(side_effect=RuntimeError("still broken"))
    out = await inbox.deliver(None, "c", "t", {"event_id": "e2"}, handler, backoff=(0, 0))
    assert out == "dead_lettered"
    assert handler.await_count == 3
    assert no_db["dlq"][0]["attempts"] == 3
    assert "still broken" in no_db["dlq"][0]["error"]
    assert ("c", "e2") not in no_db["processed"]


@pytest.mark.asyncio
async def test_permanent_error_skips_retries(no_db):
    handler = AsyncMock(side_effect=inbox.PermanentEventError("bad payload"))
    out = await inbox.deliver(None, "c", "t", {"event_id": "e3"}, handler, backoff=(0, 0))
    assert out == "dead_lettered"
    assert handler.await_count == 1


@pytest.mark.asyncio
async def test_redelivered_event_is_skipped(no_db):
    no_db["processed"].add(("c", "e4"))
    handler = AsyncMock()
    assert await inbox.deliver(None, "c", "t", {"event_id": "e4"}, handler) == "skipped"
    handler.assert_not_called()
