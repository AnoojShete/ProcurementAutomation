"""FR-03: pending bank-detail changes and stale review-queue documents get
one reminder each once past their thresholds."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.services import reminder_sweep

NOW = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)


def _factory(pending, stale):
    session = AsyncMock()
    results = []
    for rows in (pending, stale):
        r = MagicMock()
        r.all.return_value = rows
        results.append(r)
    session.execute.side_effect = results
    f = MagicMock()
    f.return_value.__aenter__.return_value = session
    return f, session


def test_due_items_are_reminded_with_their_kinds(monkeypatch):
    monkeypatch.setattr(reminder_sweep, "_hours", lambda rule, fallback: 24)
    remind = AsyncMock(return_value=True)
    monkeypatch.setattr(reminder_sweep, "remind_once", remind)
    factory, session = _factory(
        [SimpleNamespace(id="p-1", vendor_id="v-1", since=NOW - timedelta(hours=30)),
         SimpleNamespace(id="p-2", vendor_id="v-2", since=NOW - timedelta(hours=2))],
        [SimpleNamespace(id="d-1", since=NOW - timedelta(hours=48))],
    )
    sent = asyncio.run(reminder_sweep.sweep_reminders(factory, object(), now=NOW))
    assert sent == {"bank_verification_pending": 1, "review_stale": 1}
    kinds = [(c.kwargs["kind"], c.kwargs["entity_id"]) for c in remind.await_args_list]
    assert kinds == [("bank_verification_pending", "p-1"), ("review_stale", "d-1")]


def test_queries_only_open_items(monkeypatch):
    factory, session = _factory([], [])
    asyncio.run(reminder_sweep.sweep_reminders(factory, object(), now=NOW))
    sqls = [str(c.args[0]) for c in session.execute.await_args_list]
    assert "status = 'pending'" in sqls[0]                           # verified/rejected drop out
    assert "needs_review" in sqls[1] and "reviewed_at IS NULL" in sqls[1]  # reviewed drop out
