"""shared/reminders.py (FR-03): reminder.due payloads, when an item is due,
and "once per item and threshold"."""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

import shared.eventing as eventing
from shared import reminders

NOW = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)


def run(coro):
    return asyncio.run(coro)


def test_payload_shape_and_kind_check():
    since = datetime.now(timezone.utc) - timedelta(hours=30)  # waiting_hours is measured from the real clock
    p = reminders.build_reminder_due_payload("review_stale", "document", "d-1", since,
                                             "24h", "reviewer", "/app/documents/d-1")
    assert set(p) == {"kind", "entity_type", "entity_id", "waiting_since", "waiting_hours", "threshold",
                      "recipient_role", "link", "detail"}
    assert p["waiting_hours"] >= 30
    with pytest.raises(ValueError):
        reminders.build_reminder_due_payload("nope", "x", "1", NOW, "1h", "r", "/")


def test_is_due():
    assert reminders.is_due(NOW - timedelta(hours=25), 24, NOW)
    assert not reminders.is_due(NOW - timedelta(hours=23), 24, NOW)
    assert reminders.is_due((NOW - timedelta(days=3)).replace(tzinfo=None), 72, NOW)  # naive DB timestamps


def _session(already: bool):
    s = AsyncMock()
    res = MagicMock()
    res.first.return_value = (1,) if already else None
    s.execute.return_value = res
    return s


def test_remind_once_publishes_and_marks(monkeypatch):
    outbox = MagicMock()
    outbox.publish_reminder_due = AsyncMock()
    monkeypatch.setattr(eventing, "staged", lambda producer, session: outbox)
    session = _session(already=False)
    sent = run(reminders.remind_once(session, object(), kind="signature_waiting", entity_type="contract",
                                     entity_id="11111111-1111-1111-1111-111111111111", waiting_since=NOW,
                                     threshold="3d", recipient_role="signer", link="/x", service="svc"))
    assert sent is True
    outbox.publish_reminder_due.assert_awaited_once()
    marker_sql = str(session.execute.await_args_list[-1].args[0])
    assert "INSERT INTO audit_log" in marker_sql


def test_remind_once_skips_when_already_reminded(monkeypatch):
    outbox = MagicMock()
    outbox.publish_reminder_due = AsyncMock()
    monkeypatch.setattr(eventing, "staged", lambda producer, session: outbox)
    sent = run(reminders.remind_once(_session(already=True), object(), kind="signature_waiting",
                                     entity_type="contract", entity_id="11111111-1111-1111-1111-111111111111",
                                     waiting_since=NOW, threshold="3d", recipient_role="signer", link="/x",
                                     service="svc"))
    assert sent is False
    outbox.publish_reminder_due.assert_not_awaited()
