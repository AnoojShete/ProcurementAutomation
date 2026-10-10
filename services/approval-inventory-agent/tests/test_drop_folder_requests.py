"""A quote dropped into the drop folder becomes a purchase request
(app/kafka/consumer.py create_request_from_dropped_quote)."""
import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

from app.kafka import consumer
from shared.drop_folder import INBOX_UPLOADER

DOC_ID = "6f1c2c1e-0000-4000-8000-000000000001"


def run_loop(coro):
    """Own event loop, so the suite's other tests keep the default one."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _doc(**overrides):
    doc = {
        "uploaded_by": INBOX_UPLOADER, "original_filename": "acme-quote.pdf", "vendor_id": "v-1",
        "total": 450.0, "currency": "INR", "needs_review": False, "is_likely_duplicate": False,
        "extracted": {"quote_number": "Q-77", "line_items": [
            {"description": "Seat licence", "quantity": 3, "unit_price": 150.0, "bank_account_number": "x"},
        ]},
    }
    doc.update(overrides)
    return doc


@pytest.fixture
def run(monkeypatch):
    """Runs the handler against a fake session: execute() returns the
    document row, then whether a request already exists for it."""
    def _run(doc, existing=None):
        session = AsyncMock()
        session.execute.side_effect = [
            MagicMock(mappings=MagicMock(return_value=MagicMock(first=MagicMock(return_value=doc)))),
            MagicMock(first=MagicMock(return_value=existing)),
        ]
        factory = MagicMock()
        factory.return_value.__aenter__ = AsyncMock(return_value=session)
        factory.return_value.__aexit__ = AsyncMock(return_value=False)
        monkeypatch.setattr(consumer, "async_session_factory", factory)
        service = MagicMock()
        service.create_request = AsyncMock(return_value=MagicMock(id="pr-1", spend_tier="auto", status="approved"))
        outcome = run_loop(consumer.create_request_from_dropped_quote(DOC_ID, service_factory=lambda s: service))
        return outcome, service.create_request
    return _run


def test_drop_folder_quote_becomes_a_request_linked_to_the_document(run):
    outcome, create = run(_doc())
    assert outcome == "created"
    data = create.await_args.args[0]
    assert create.await_args.kwargs == {"document_id": DOC_ID}
    assert data.requested_by == INBOX_UPLOADER
    assert data.vendor_id == "v-1" and data.amount == 450.0 and data.currency == "INR"
    assert data.request_type == "saas"
    # Only item fields are copied — nothing else from the extraction.
    assert data.items == [{"description": "Seat licence", "quantity": 3, "unit_price": 150.0}]
    assert "acme-quote.pdf" in data.comments and "Q-77" in data.comments


@pytest.mark.parametrize("doc, outcome", [
    (_doc(uploaded_by="requester@demo.example.com"), "not_from_drop_folder"),
    (_doc(needs_review=True), "needs_review"),
    (_doc(is_likely_duplicate=True), "duplicate"),
    (_doc(vendor_id=None), "incomplete"),
    (_doc(total=0), "incomplete"),
])
def test_no_request_when_it_should_wait_or_stop(run, doc, outcome):
    result, create = run(doc)
    assert result == outcome
    create.assert_not_awaited()


def test_redelivered_event_does_not_create_a_second_request(run):
    outcome, create = run(_doc(), existing=("pr-1",))
    assert outcome == "already_created"
    create.assert_not_awaited()


def test_extracted_json_as_text_is_handled(run):
    outcome, create = run(_doc(extracted='{"line_items": [{"description": "Laptop", "quantity": 1}]}'))
    assert outcome == "created"
    assert create.await_args.args[0].items == [{"description": "Laptop", "quantity": 1}]
