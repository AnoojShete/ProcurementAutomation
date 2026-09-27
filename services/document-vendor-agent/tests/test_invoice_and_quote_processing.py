"""Tests for invoice 3-way matching and quote processing."""
import os
import sys
_service_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _service_root not in sys.path:
    sys.path.insert(0, _service_root)

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from app.services.pipeline import (
    invoice_matching_agent,
    duplicate_detection_agent,
    vendor_matching_agent,
)


@pytest.mark.asyncio
class TestInvoiceThreeWayMatching:
    """invoice_matching_agent delegates to approval-inventory-agent's invoice
    ledger (POST /invoices/match) and maps its verdict onto the envelope."""

    @staticmethod
    def _envelope(total, lines=None, hold=False):
        return {
            "document_id": "doc-inv-1", "document_type": "invoice", "vendor_id": "vendor-123",
            "extracted_fields": {
                "total": total, "invoice_number": "INV-2026-001", "document_number": "INV-2026-001",
                "line_items": lines or [],
            },
            "payment_hold": hold, "payment_hold_reason": "vendor bank details awaiting verification" if hold else None,
            "agent_results": {},
        }

    @staticmethod
    def _ledger(result):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"data": result}
        return patch("httpx.AsyncClient.post", return_value=resp)

    async def test_matched_books_and_emits_event(self):
        producer = AsyncMock()
        result = {"status": "matched", "request_id": "11111111-2222-3333-4444-555555555555",
                  "issues": [], "remaining_before": 1000.0, "remaining_after": 0.0, "allocations": []}
        lines = [{"description": "Laptop", "quantity": 1, "unit_price": 847.46}]
        with self._ledger(result) as post:
            env = await invoice_matching_agent(AsyncMock(), producer, self._envelope(1000.0, lines, hold=True))

        body = post.call_args.kwargs["json"]
        assert body["lines"] == [{"description": "Laptop", "quantity": 1, "unit_price": 847.46}]
        assert body["payment_hold"] is True
        assert env["matched_po_id"] == result["request_id"]
        assert env["matched_po_number"] == "PO-11111111"
        assert env["unmatched_invoice"] is False
        assert env.get("needs_review_forced") is not True
        producer.publish_invoice_matched.assert_awaited_once()
        assert producer.publish_invoice_matched.call_args.kwargs["purchase_request_id"] == result["request_id"]

    async def test_partial_invoice_is_a_match(self):
        producer = AsyncMock()
        result = {"status": "partial", "request_id": "11111111-2222-3333-4444-555555555555",
                  "issues": [], "remaining_before": 2000.0, "remaining_after": 1000.0, "allocations": []}
        with self._ledger(result):
            env = await invoice_matching_agent(AsyncMock(), producer, self._envelope(1000.0))
        assert env["unmatched_invoice"] is False
        assert env["invoice_match"]["remaining_after"] == 1000.0
        producer.publish_invoice_matched.assert_awaited_once()

    async def test_overbilled_invoice_goes_to_review_and_is_not_booked(self):
        producer = AsyncMock()
        issue = "'Laptop': unit price 900.00 is above the agreed 847.46"
        result = {"status": "variance", "request_id": "po-1", "issues": [issue], "allocations": []}
        with self._ledger(result):
            env = await invoice_matching_agent(AsyncMock(), producer, self._envelope(1062.0))
        assert env["needs_review_forced"] is True
        assert env["invoice_variance"] == [issue]
        assert env["matched_po_id"] is None
        producer.publish_invoice_matched.assert_not_called()

    async def test_zero_matches_routes_to_human_review_unmatched_invoice(self):
        producer = AsyncMock()
        with self._ledger({"status": "no_match", "issues": ["no purchase request fits"]}):
            env = await invoice_matching_agent(AsyncMock(), producer, self._envelope(5500.0))
        assert env["matched_po_id"] is None
        assert env["unmatched_invoice"] is True
        assert env["needs_review_forced"] is True
        producer.publish_invoice_matched.assert_not_called()

    async def test_ambiguous_forces_human_review_and_lists_candidates(self):
        producer = AsyncMock()
        candidates = [{"request_id": "po-1"}, {"request_id": "po-2"}]
        with self._ledger({"status": "ambiguous", "candidates": candidates, "issues": ["2 could take it"]}):
            env = await invoice_matching_agent(AsyncMock(), producer, self._envelope(2000.0))
        assert env["needs_review_forced"] is True
        assert env["candidate_pos"] == candidates
        producer.publish_invoice_matched.assert_not_called()

    async def test_ledger_down_is_retried_not_filed_as_unmatched(self):
        from app.services.pipeline import LedgerUnavailableError
        producer = AsyncMock()
        with patch("httpx.AsyncClient.post", side_effect=httpx.ConnectError("down")):
            with pytest.raises(LedgerUnavailableError):
                await invoice_matching_agent(AsyncMock(), producer, self._envelope(1000.0))
        producer.publish_invoice_matched.assert_not_called()

    async def test_ledger_server_error_is_retried(self):
        from app.services.pipeline import LedgerUnavailableError
        resp = MagicMock(status_code=503, text="unavailable")
        with patch("httpx.AsyncClient.post", return_value=resp):
            with pytest.raises(LedgerUnavailableError):
                await invoice_matching_agent(AsyncMock(), AsyncMock(), self._envelope(1000.0))

    async def test_ledger_rejecting_the_request_goes_to_review(self):
        resp = MagicMock(status_code=422, text="bad payload")
        with patch("httpx.AsyncClient.post", return_value=resp):
            env = await invoice_matching_agent(AsyncMock(), AsyncMock(), self._envelope(1000.0))
        assert env["needs_review_forced"] is True and env["unmatched_invoice"] is True


@pytest.mark.asyncio
class TestQuoteProcessing:
    async def test_duplicate_check_skipped_for_quotes(self):
        envelope = {
            "document_id": "doc-quote-1",
            "document_type": "quote",
            "vendor_id": "vendor-123",
            "extracted_fields": {
                "total": 999.0,
                "quote_number": "Q-123",
            },
        }
        mock_db = AsyncMock()

        result = await duplicate_detection_agent(mock_db, envelope)
        assert result["is_duplicate"] is False
        assert result["duplicate_of_document_id"] is None
        trail = result.get("_agent_trail", [])
        dup_step = next((s for s in trail if s.agent_name == "duplicate_detection_agent"), None)
        assert dup_step is not None
        assert dup_step.next_action == "skipped_non_invoice"

    async def test_quote_saved_to_vendor_quotes_table(self):
        envelope = {
            "document_id": "doc-quote-2",
            "document_type": "quote",
            "extracted_fields": {
                "vendor_name_raw": "Dell India",
                "quote_number": "Q-8888",
                "total": 125000.0,
                "currency": "INR",
                "valid_until": "2026-12-31",
                "line_items": [{"description": "Laptops", "category": "hardware"}],
            },
        }

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_producer = AsyncMock()

        fake_vendor = MagicMock()
        fake_vendor.id = "vendor-dell"
        fake_vendor.normalized_name = "dell india"

        fake_match = MagicMock()
        fake_match.vendor = fake_vendor
        fake_match.match_type = "existing"
        fake_match.match_confidence = 0.95

        with patch("app.services.pipeline.find_or_create_vendor", return_value=fake_match):
            result = await vendor_matching_agent(mock_db, mock_producer, envelope, uploaded_by="tester@company.com")

        assert result["vendor_id"] == "vendor-dell"
        assert result["payment_change_flagged"] is False
        # Verify VendorQuote was added to db
        added_objs = [call.args[0] for call in mock_db.add.call_args_list]
        quote_objs = [obj for obj in added_objs if obj.__class__.__name__ == "VendorQuote"]
        assert len(quote_objs) == 1
        saved_quote = quote_objs[0]
        assert saved_quote.quote_number == "Q-8888"
        assert saved_quote.total == 125000.0
        assert saved_quote.is_binding is False


def test_po_reference_extraction():
    from app.services.pipeline import find_po_reference
    assert find_po_reference("Bill To: Acme\nPO Reference: PO-9e085e38\nTotal: 10") == "PO-9E085E38"
    assert find_po_reference("Purchase Order #: PO-049F69BD") == "PO-049F69BD"
    assert find_po_reference("Invoice Number: INV-2026-001") is None
