"""An invoice with no request to match ("Create a purchase request from
this invoice") is booked once that request is approved. approval.decided
is published per level and before the workflow saves the status."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.kafka import consumer

CHAIN = ["dept_manager", "finance_head"]


def _db_returning(row):
    db = AsyncMock()
    result = MagicMock()
    result.first.return_value = row
    db.execute.return_value = result
    factory = MagicMock()
    factory.return_value.__aenter__.return_value = db
    return factory


def _row(status, document_id="doc-1"):
    return SimpleNamespace(document_id=document_id, status=status, approval_chain=CHAIN)


def _event(level="level_2_finance_head", decision="approved"):
    return {"request_id": "r1", "decision": decision, "decision_level": level}


@pytest.fixture
def rematch(monkeypatch):
    m = AsyncMock(return_value={"status": "matched"})
    monkeypatch.setattr(consumer, "rematch_invoice", m)
    return m


@pytest.mark.asyncio
async def test_approved_request_books_its_invoice(monkeypatch, rematch):
    monkeypatch.setattr(consumer, "async_session_factory", _db_returning(_row("approved")))
    await consumer._handle_approval_decided(None, _event())
    assert rematch.await_args.args[2] == "doc-1"


@pytest.mark.asyncio
async def test_final_level_before_status_is_saved_is_retried(monkeypatch, rematch):
    monkeypatch.setattr(consumer, "async_session_factory", _db_returning(_row("pending_approval")))
    with pytest.raises(consumer.RequestNotApprovedYet):
        await consumer._handle_approval_decided(None, _event("level_2_finance_head"))
    rematch.assert_not_called()


@pytest.mark.asyncio
async def test_earlier_level_does_nothing(monkeypatch, rematch):
    monkeypatch.setattr(consumer, "async_session_factory", _db_returning(_row("pending_approval")))
    await consumer._handle_approval_decided(None, _event("level_1_dept_manager"))
    rematch.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("row,event", [
    (_row("approved", document_id=None), _event()),    # request not created from a document
    (_row("rejected"), _event()),
    (_row("approved"), _event(decision="rejected")),
])
async def test_nothing_to_book(monkeypatch, rematch, row, event):
    monkeypatch.setattr(consumer, "async_session_factory", _db_returning(row))
    await consumer._handle_approval_decided(None, event)
    rematch.assert_not_called()
