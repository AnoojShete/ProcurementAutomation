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
    async def test_exactly_one_match_emits_event(self):
        envelope = {
            "document_id": "doc-inv-1",
            "document_type": "invoice",
            "vendor_id": "vendor-123",
            "extracted_fields": {
                "total": 1000.0,
                "invoice_number": "INV-2026-001",
                "document_number": "INV-2026-001",
            },
            "agent_results": {},
        }

        mock_db = AsyncMock()
        mock_producer = AsyncMock()
        mock_producer.publish_invoice_matched = AsyncMock()

        candidate = {
            "id": "po-456",
            "po_number": "PO-2026-999",
            "amount": 1000.0,
            "status": "approved",
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": [candidate]}

        with patch("httpx.AsyncClient.get", return_value=mock_resp):
            result = await invoice_matching_agent(mock_db, mock_producer, envelope)

        assert result["matched_po_id"] == "po-456"
        assert result["matched_po_number"] == "PO-2026-999"
        assert result["unmatched_invoice"] is False
        assert result.get("needs_review_forced") is not True

        mock_producer.publish_invoice_matched.assert_awaited_once_with(
            document_id="doc-inv-1",
            invoice_number="INV-2026-001",
            purchase_request_id="po-456",
            po_number="PO-2026-999",
            vendor_id="vendor-123",
            invoice_total=1000.0,
            po_total=1000.0,
        )

    async def test_zero_matches_routes_to_human_review_unmatched_invoice(self):
        envelope = {
            "document_id": "doc-inv-2",
            "document_type": "invoice",
            "vendor_id": "vendor-123",
            "extracted_fields": {
                "total": 5500.0,
                "invoice_number": "INV-2026-002",
            },
            "agent_results": {},
        }

        mock_db = AsyncMock()
        mock_producer = AsyncMock()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": []}

        with patch("httpx.AsyncClient.get", return_value=mock_resp):
            result = await invoice_matching_agent(mock_db, mock_producer, envelope)

        assert result["matched_po_id"] is None
        assert result["unmatched_invoice"] is True
        assert result["needs_review_forced"] is True
        mock_producer.publish_invoice_matched.assert_not_called()

    async def test_multiple_matches_forces_human_review_and_lists_candidates(self):
        envelope = {
            "document_id": "doc-inv-3",
            "document_type": "invoice",
            "vendor_id": "vendor-123",
            "extracted_fields": {
                "total": 2000.0,
                "invoice_number": "INV-2026-003",
            },
            "agent_results": {},
        }

        mock_db = AsyncMock()
        mock_producer = AsyncMock()

        candidates = [
            {"id": "po-1", "po_number": "PO-1", "amount": 2000.0},
            {"id": "po-2", "po_number": "PO-2", "amount": 2000.0},
        ]

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": candidates}

        with patch("httpx.AsyncClient.get", return_value=mock_resp):
            result = await invoice_matching_agent(mock_db, mock_producer, envelope)

        assert result["matched_po_id"] is None
        assert result["needs_review_forced"] is True
        assert len(result["candidate_pos"]) == 2
        mock_producer.publish_invoice_matched.assert_not_called()


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
