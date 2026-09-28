"""app/services/learning.py — learning from reviewer corrections."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import learning

RAW = """Zenith Test Systems Pvt Ltd
TAX INVOICE
Bill#: ZT-88/2026
Invoice Date: 2026-09-01
Subtotal: 3,300.00
Tax (18%): 594.00
Amount Due: INR 3,894.00
"""


def test_derive_label_for_amount_token_and_date():
    assert learning.derive_label(RAW, "amount", "3894.00") == "Amount Due"
    assert learning.derive_label(RAW, "token", "ZT-88/2026") == "Bill"
    assert learning.derive_label(RAW, "date", "2026-09-01") == "Invoice Date"


def test_derive_label_none_when_value_absent_or_unlabelled():
    assert learning.derive_label(RAW, "amount", "999.00") is None
    assert learning.derive_label("3,894.00\n", "amount", "3894.00") is None


def test_read_by_label_is_the_inverse():
    assert learning.read_by_label(RAW, "Amount Due", "amount") == "3894.00"
    assert learning.read_by_label(RAW, "bill", "token") == "ZT-88/2026"
    assert learning.read_by_label(RAW, "Invoice Date", "date") == "2026-09-01"
    assert learning.read_by_label(RAW, "Grand Total", "amount") is None


def test_corrected_fields_ignores_unchanged_and_format_only_differences():
    before = {"total": 3300.0, "invoice_number": "ZT-88/2026", "document_date": "2026-09-01"}
    after = {"total": "3,894.00", "invoice_number": "ZT-88/2026", "document_date": "2026-09-01"}
    assert learning.corrected_fields(before, after) == {"total": (3300.0, "3,894.00")}


@pytest.mark.parametrize("reviews,clean,expected", [
    (3, 3, (0.8, "default")),     # not enough evidence yet
    (10, 10, (0.65, "relaxed")),  # reviewers keep confirming this vendor unchanged
    (10, 3, (0.9, "strict")),     # this vendor keeps needing fixes
    (10, 7, (0.8, "default")),
])
def test_calibrated_threshold(reviews, clean, expected):
    assert learning.calibrated_threshold(0.8, reviews, clean) == expected


def _envelope(total):
    return {
        "document_id": "d1", "vendor_id": "v1", "raw_text": RAW,
        "extracted_fields": {"total": total, "invoice_number": "ZT-88/2026", "document_number": "ZT-88/2026"},
        "field_confidences": {"total": 0.4, "document_number": 0.9},
    }


@pytest.mark.asyncio
async def test_learned_label_corrects_the_field(monkeypatch):
    monkeypatch.setattr(learning, "vendor_hints", AsyncMock(return_value={"total": ("Amount Due", 2)}))
    monkeypatch.setattr(learning, "vendor_review_threshold",
                        AsyncMock(return_value={"threshold": 0.8, "mode": "default", "reviews": 2, "clean": 0}))
    env = await learning.vendor_learning_agent(AsyncMock(), _envelope(3300.0))  # picked up the subtotal
    assert env["extracted_fields"]["total"] == 3894.0
    assert env["field_confidences"]["total"] == 0.95
    assert env["learned_fields"][0]["action"] == "corrected"
    assert env["learned_fields"][0]["previous"] == 3300.0


@pytest.mark.asyncio
async def test_matching_value_is_confirmed_not_changed(monkeypatch):
    monkeypatch.setattr(learning, "vendor_hints", AsyncMock(return_value={"total": ("Amount Due", 3)}))
    monkeypatch.setattr(learning, "vendor_review_threshold",
                        AsyncMock(return_value={"threshold": 0.65, "mode": "relaxed", "reviews": 9, "clean": 9}))
    env = await learning.vendor_learning_agent(AsyncMock(), _envelope(3894.0))
    assert env["learned_fields"][0]["action"] == "confirmed"
    assert env["review_threshold"]["threshold"] == 0.65


@pytest.mark.asyncio
async def test_record_review_stores_feedback_and_hint():
    db = AsyncMock()
    doc = MagicMock(id="d1", vendor_id="v1", raw_text=RAW)
    out = await learning.record_review(db, doc, {"total": 3300.0}, {"total": 3894.0}, "reviewer@acme.test")
    assert out == {"corrected": ["total"], "learned": [{"field": "total", "label": "Amount Due"}]}
    statements = [str(c.args[0]) for c in db.execute.call_args_list]
    assert any("INSERT INTO extraction_feedback" in q for q in statements)
    assert any("INSERT INTO vendor_field_hints" in q for q in statements)
    assert any("INSERT INTO review_outcomes" in q for q in statements)
