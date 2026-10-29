"""FR-09: every business rule this service reads changes behaviour when an
admin changes it. Each test sets the rule to two values through the shared
rules-engine cache (the same path a live rule takes) and checks the effect.
docs/business-rules.md lists these tests per rule."""
import asyncio
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import shared.rules_engine as rules_engine


@pytest.fixture
def rule(monkeypatch):
    rules_engine.clear_cache()
    monkeypatch.setattr(rules_engine, "fetch_all_rules", lambda: {})
    yield rules_engine.update_rule_cache
    rules_engine.clear_cache()


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_document_confidence_review_threshold(rule):
    from app.services.confidence import needs_review
    rule("document.confidence_review_threshold", 0.9)
    assert needs_review(0.85) is True
    rule("document.confidence_review_threshold", 0.8)
    assert needs_review(0.85) is False


def _route(quality, file_type="image"):
    from app.services import extraction_router
    from app.services.ocr import ExtractionResult
    seen = {}

    def fake_extract(data, filename, content_type, timeout, preprocess):
        seen["preprocess"] = preprocess
        return ExtractionResult(text="Invoice 42 Total 100.00", method="paddleocr", file_type=file_type, text_quality=quality)

    with patch.object(extraction_router, "extract_text_isolated", fake_extract), \
            patch.object(extraction_router, "_layoutlm_image_fallback", lambda d, e: ("Invoice 42", 0.7)), \
            patch.object(extraction_router, "_log_to_db", lambda *a: None):
        result = run(extraction_router.route_extraction(MagicMock(), "doc-1", b"x", "a.png", "image/png"))
    return result, seen


def test_document_image_preprocessing(rule):
    rule("document.image_preprocessing", True)
    assert _route(0.9)[1]["preprocess"] is True
    rule("document.image_preprocessing", False)
    assert _route(0.9)[1]["preprocess"] is False


def test_document_extraction_fallback_confidence_threshold(rule):
    rule("document.extraction_fallback_confidence_threshold", 0.5)
    assert _route(0.45)[0].fallback_triggered is True
    rule("document.extraction_fallback_confidence_threshold", 0.4)
    assert _route(0.45)[0].fallback_triggered is False


def _duplicate(total=100.0, days_apart=6, number="INV-1009"):
    from app.services.duplicate_detection import check_duplicate_invoice
    earlier = SimpleNamespace(id="d-0", total=102.0, document_date=date(2026, 10, 1), document_number="INV-1000")
    db = AsyncMock()
    res = MagicMock()
    res.scalars.return_value.all.return_value = [earlier]
    db.execute.return_value = res
    when = (date(2026, 10, 1) + timedelta(days=days_apart)).isoformat()
    return run(check_duplicate_invoice(db, "v-1", total, when, number)).is_duplicate


def test_document_duplicate_invoice_amount_tolerance_pct(rule):
    rule("document.duplicate_invoice_date_window_days", 30)
    rule("vendor.duplicate_invoice_number_fuzzy_threshold", 50)
    rule("document.duplicate_invoice_amount_tolerance_pct", 0.01)   # 102 vs 100 is 2 %
    assert _duplicate() is False
    rule("document.duplicate_invoice_amount_tolerance_pct", 0.03)
    assert _duplicate() is True


def test_document_duplicate_invoice_date_window_days(rule):
    rule("document.duplicate_invoice_amount_tolerance_pct", 0.05)
    rule("vendor.duplicate_invoice_number_fuzzy_threshold", 50)
    rule("document.duplicate_invoice_date_window_days", 5)           # 6 days apart
    assert _duplicate() is False
    rule("document.duplicate_invoice_date_window_days", 7)
    assert _duplicate() is True


def test_vendor_duplicate_invoice_number_fuzzy_threshold(rule):
    rule("document.duplicate_invoice_amount_tolerance_pct", 0.05)
    rule("document.duplicate_invoice_date_window_days", 30)
    rule("vendor.duplicate_invoice_number_fuzzy_threshold", 95)      # INV-1009 vs INV-1000 ≈ 88
    assert _duplicate() is False
    rule("vendor.duplicate_invoice_number_fuzzy_threshold", 80)
    assert _duplicate() is True


def _lookalike_flagged(score):
    from app.services import pipeline
    from app.services.vendor_matching import VendorMatchResult
    def vendor(vid, name):
        return SimpleNamespace(id=vid, name=name, normalized_name=name.lower(), bank_account_number=None,
                               routing_code=None, payment_beneficiary_name=None,
                               payment_details_pending_verification=False)
    real, new = vendor("v-real", "Dell Technologies"), vendor("v-new", "De1l Technologies")
    match = VendorMatchResult(vendor=new, match_type="new", match_confidence=1.0, closest_existing=real,
                              closest_score=score)
    env = {"document_id": "doc-1", "document_type": "invoice",
           "extracted_fields": {"vendor_name_raw": "De1l Technologies"}, "_agent_trail": []}
    with patch.object(pipeline, "find_or_create_vendor", AsyncMock(return_value=match)), \
            patch.object(pipeline, "write_audit_log", AsyncMock()):
        out = run(pipeline.vendor_matching_agent(AsyncMock(), AsyncMock(), env, "u@x"))
    return "lookalike_vendor" in out


def test_vendor_lookalike_min_similarity(rule):
    rule("vendor.lookalike_min_similarity", 70)
    assert _lookalike_flagged(75.0) is True
    rule("vendor.lookalike_min_similarity", 80)
    assert _lookalike_flagged(75.0) is False


def test_vendor_petty_tier_max_amount(rule):
    from app.services.vendor_tier_service import VendorTier, classify_tier
    rule("vendor.standard_tier_max_amount", 1_000_000)
    rule("vendor.petty_tier_max_amount", 10_000)
    assert classify_tier(20_000) == VendorTier.STANDARD
    rule("vendor.petty_tier_max_amount", 50_000)
    assert classify_tier(20_000) == VendorTier.PETTY


def test_vendor_standard_tier_max_amount(rule):
    from app.services.vendor_tier_service import VendorTier, classify_tier
    rule("vendor.petty_tier_max_amount", 10_000)
    rule("vendor.standard_tier_max_amount", 100_000)
    assert classify_tier(200_000) == VendorTier.STRATEGIC
    rule("vendor.standard_tier_max_amount", 500_000)
    assert classify_tier(200_000) == VendorTier.STANDARD


def _spend_cutoff_days():
    from app.services.vendor_tier_service import get_vendor_spend_90d
    db = AsyncMock()
    db.execute.return_value = MagicMock(scalar=MagicMock(return_value=0.0))
    run(get_vendor_spend_90d(db, "v-1"))
    stmt = db.execute.await_args.args[0]
    cutoff = next(v for v in stmt.compile().params.values() if isinstance(v, datetime))
    return round((datetime.now(timezone.utc) - cutoff).total_seconds() / 86400)


def test_vendor_structuring_detection_window_days(rule):
    rule("vendor.structuring_detection_window_days", 90)
    assert _spend_cutoff_days() == 90
    rule("vendor.structuring_detection_window_days", 30)
    assert _spend_cutoff_days() == 30


NOW = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)


def _sweep(monkeypatch, bank_since=None, review_since=None):
    from app.services import reminder_sweep
    session = AsyncMock()
    rows = [[SimpleNamespace(id="p-1", vendor_id="v-1", since=bank_since)] if bank_since else [],
            [SimpleNamespace(id="d-1", since=review_since)] if review_since else []]
    results = []
    for r in rows:
        m = MagicMock()
        m.all.return_value = r
        results.append(m)
    session.execute.side_effect = results
    factory = MagicMock()
    factory.return_value.__aenter__.return_value = session
    monkeypatch.setattr(reminder_sweep, "remind_once", AsyncMock(return_value=True))
    return run(reminder_sweep.sweep_reminders(factory, object(), now=NOW))


def test_vendor_bank_verification_reminder_hours(rule, monkeypatch):
    rule("vendor.bank_verification_reminder_hours", 24)
    assert _sweep(monkeypatch, bank_since=NOW - timedelta(hours=30))["bank_verification_pending"] == 1
    rule("vendor.bank_verification_reminder_hours", 48)
    assert _sweep(monkeypatch, bank_since=NOW - timedelta(hours=30))["bank_verification_pending"] == 0


def test_document_review_reminder_hours(rule, monkeypatch):
    rule("document.review_reminder_hours", 24)
    assert _sweep(monkeypatch, review_since=NOW - timedelta(hours=30))["review_stale"] == 1
    rule("document.review_reminder_hours", 48)
    assert _sweep(monkeypatch, review_since=NOW - timedelta(hours=30))["review_stale"] == 0


def _pruned_days():
    from app.services.event_monitor import EventMonitor
    session = AsyncMock()
    session.execute.return_value = MagicMock(rowcount=0)
    factory = MagicMock()
    factory.return_value.__aenter__.return_value = session
    run(EventMonitor("kafka:9092", session_factory=factory).prune())
    return session.execute.await_args.args[1]["d"]


def test_monitor_event_log_retention_days(rule):
    rule("monitor.event_log_retention_days", 14)
    assert _pruned_days() == 14
    rule("monitor.event_log_retention_days", 3)
    assert _pruned_days() == 3


def test_dev_force_model_fallback(rule, monkeypatch):
    """FR-08: forcing the extraction router's primary to fail shows the
    LayoutLMv3 fallback (reason "forced"), even for a good reading — in
    development only."""
    rule("document.extraction_fallback_confidence_threshold", 0.5)
    rule("dev.force_model_fallback", [])
    assert _route(0.95)[0].fallback_triggered is False
    rule("dev.force_model_fallback", ["extraction"])
    forced = _route(0.95)[0]
    assert forced.fallback_triggered is True and forced.fallback_reason == "forced"
    assert forced.route_name == "layoutlmv3_fallback"
    monkeypatch.setenv("APP_ENV", "production")
    assert _route(0.95)[0].fallback_triggered is False


# ── Phase 4: GST check (app/services/pipeline.tax_agent) ────────────────────

def _gst_stage(lines, vendor=None):
    from app.services import pipeline
    from app.services.field_extraction import extract_fields
    text = "\n".join(lines)
    d = extract_fields(text, "invoice")[0].to_dict("invoice")
    env = {"document_id": "d", "document_type": "invoice", "raw_text": text, "extracted_fields": d, "vendor_id": "v",
           "file_type": "pdf", "fx": {"total_inr": d["total"]}, "_agent_trail": []}
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(first=MagicMock(return_value=vendor)))
    rates = {"8471": {"rate_pct": 18.0, "category": "hardware"}}
    with patch.object(pipeline, "load_gst_rates", AsyncMock(return_value=rates)):
        return run(pipeline.tax_agent(db, None, env, b""))["tax_check"]


def _gst_lines(**kw):
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
    from gst_invoice_lib import gst_invoice
    items = [{"name": "Latitude 5540 Laptop", "hsn": "8471", "quantity": 2, "unit_price": 80000.0}]
    return gst_invoice({"name": "Kaveri Infotech", "gstin": "29AABCD5678E1ZG"}, "29AAACA1234B1ZE", "INV-1",
                       date(2026, 10, 15), items, **kw)[0]


def test_gst_buyer_gstin(rule):
    rule("gst.buyer_gstin", "29AAACA1234B1ZE")
    assert _gst_stage(_gst_lines())["status"] == "ok"
    rule("gst.buyer_gstin", "29AABCD5678E2ZF")
    assert _gst_stage(_gst_lines())["status"] == "flagged"


def test_gst_tax_tolerance_inr(rule):
    rule("gst.buyer_gstin", "29AAACA1234B1ZE")
    lines = [ln.replace("Total: 188,800.00", "Total: 188,803.00") for ln in _gst_lines()]
    rule("gst.tax_tolerance_inr", 1.0)
    assert _gst_stage(lines)["status"] == "flagged"
    rule("gst.tax_tolerance_inr", 5.0)
    assert _gst_stage(lines)["status"] == "ok"


def test_gst_require_breakdown(rule):
    lines = ["Vendor Co", "Invoice Number: INV-2", "Subtotal: 1,000.00", "Tax (18%): 180.00", "Total: 1,180.00"]
    rule("gst.require_breakdown", False)
    assert _gst_stage(lines)["status"] == "incomplete"
    rule("gst.require_breakdown", True)
    assert _gst_stage(lines)["status"] == "flagged"


def test_gst_einvoice_required_turnover_inr(rule):
    rule("gst.buyer_gstin", "29AAACA1234B1ZE")
    vendor = SimpleNamespace(gstin=None, country="IN", annual_turnover_inr=80_000_000)
    rule("gst.einvoice_required_turnover_inr", 50_000_000)
    assert _gst_stage(_gst_lines(), vendor)["status"] == "flagged"
    rule("gst.einvoice_required_turnover_inr", 100_000_000)
    assert _gst_stage(_gst_lines(), vendor)["status"] == "ok"


def test_document_upload_max_files_per_batch(rule):
    from fastapi import HTTPException
    from app.api.batches import BatchFileItem, CreateBatchRequest, create_document_batch
    files = [BatchFileItem(client_file_id=str(i), client_relative_path=f"f{i}.pdf", filename=f"f{i}.pdf",
                           file_size_bytes=10) for i in range(3)]
    payload = CreateBatchRequest(total_files=3, files=files)
    user = SimpleNamespace(id="u1", email="req@acme.test", role="requester")

    def rejected(limit):
        rule("document.upload_max_files_per_batch", limit)
        db = MagicMock()
        db.commit = AsyncMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        try:
            run(create_document_batch(payload, user=user, db=db))
        except HTTPException as e:
            return e.status_code == 400 and "maximum limit" in str(e.detail)
        return False

    assert rejected(2) is True
    assert rejected(5) is False
