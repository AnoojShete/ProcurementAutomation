"""FR-03: contracts waiting longer than contract.signature_reminder_days
get one signature reminder; newer ones don't."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.services import reminder_sweep

NOW = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)


def _factory(rows):
    session = AsyncMock()
    res = MagicMock()
    res.all.return_value = rows
    session.execute.return_value = res
    f = MagicMock()
    f.return_value.__aenter__.return_value = session
    return f, session


def test_only_contracts_past_the_threshold_are_reminded(monkeypatch):
    monkeypatch.setattr(reminder_sweep, "signature_reminder_days", lambda: 3)
    remind = AsyncMock(return_value=True)
    monkeypatch.setattr(reminder_sweep, "remind_once", remind)
    rows = [SimpleNamespace(id="c-old", request_id="r1", since=NOW - timedelta(days=4)),
            SimpleNamespace(id="c-new", request_id="r2", since=NOW - timedelta(days=1))]
    factory, session = _factory(rows)
    assert asyncio.run(reminder_sweep.sweep_signature_reminders(factory, object(), now=NOW)) == 1
    kwargs = remind.await_args.kwargs
    assert kwargs["entity_id"] == "c-old" and kwargs["threshold"] == "3d" and kwargs["kind"] == "signature_waiting"
    session.commit.assert_awaited()


def test_query_only_looks_at_contracts_still_waiting(monkeypatch):
    # Signing moves the contract out of pending_signature, so it is never a
    # candidate again — the "not after the action is taken" half.
    factory, session = _factory([])
    asyncio.run(reminder_sweep.sweep_signature_reminders(factory, object(), now=NOW))
    assert "c.status = 'pending_signature'" in str(session.execute.await_args.args[0])
