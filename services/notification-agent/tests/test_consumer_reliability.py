"""FR-31: the notification consumer retries and dead-letters failed events
instead of dropping them, and /health turns unhealthy when the consumer
has stopped (it once stopped silently for three days after a failed
Kafka login)."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.kafka import consumer as c

EVENT = {"event_id": "e-1", "event_type": "contract.signed", "schema_version": 1,
         "payload": {"contract_id": "c-1"}}


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_dispatch_raises_when_the_handler_fails():
    failing = AsyncMock(side_effect=RuntimeError("SMTP down"))
    with patch.dict(c._HANDLERS, {"contract.signed": failing}), \
            patch.object(c, "async_session_factory", MagicMock()):
        with pytest.raises(RuntimeError):
            run(c.dispatch("contract.signed", EVENT))


def test_dispatch_ignores_unknown_event_types():
    run(c.dispatch("x", {"event_id": "e-2", "event_type": "nobody.handles.this", "payload": {}}))


def test_failing_event_is_retried_then_dead_lettered():
    from shared.eventing import inbox
    failing = AsyncMock(side_effect=RuntimeError("SMTP down"))
    with patch.dict(c._HANDLERS, {"contract.signed": failing}), \
            patch.object(c, "async_session_factory", MagicMock()), \
            patch.object(inbox, "already_processed", AsyncMock(return_value=False)), \
            patch.object(inbox, "mark_processed", AsyncMock()) as marked, \
            patch.object(inbox, "dead_letter", AsyncMock(return_value="dlq-1")) as dlq:
        outcome = run(inbox.deliver(MagicMock(), c.CONSUMER_NAME, "contract.signed", EVENT,
                                    lambda: c.dispatch("contract.signed", EVENT), backoff=(0, 0)))
    assert outcome == "dead_lettered"
    assert failing.await_count == 3
    marked.assert_not_awaited()
    assert dlq.await_args.args[1] == "notification-agent" and "SMTP down" in dlq.await_args.args[4]


def test_failed_kafka_login_marks_the_consumer_stopped():
    with patch.object(c, "AIOKafkaConsumer", MagicMock(return_value=MagicMock(stop=AsyncMock()))), \
            patch.object(c, "with_retry", AsyncMock(side_effect=RuntimeError("SASL authentication failed"))):
        run(c.start_consumer(None))
    assert c.CONSUMER_STATE["status"] == "stopped"
    assert "SASL authentication failed" in c.CONSUMER_STATE["error"]


def _client():
    from app.api import health
    app = FastAPI()
    app.include_router(health.router)
    return TestClient(app)


class _DB:
    async def __aenter__(self):
        s = MagicMock()
        s.execute = AsyncMock()
        return s

    async def __aexit__(self, *a):
        return False


@pytest.mark.parametrize("state,code", [("running", 200), ("starting", 200), ("stopped", 503)])
def test_health_follows_the_consumer(state, code):
    with patch.dict(c.CONSUMER_STATE, {"status": state, "error": None}), \
            patch("app.api.health.async_session_factory", lambda: _DB()):
        r = _client().get("/health")
    assert r.status_code == code
    assert r.json()["dependencies"]["kafka_consumer"] == state
