"""Pipeline failure handling: a slow/unreadable file fails cleanly and
fast; an infrastructure error is retried, not turned into a failure."""
import io
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from app.services import document_service, ocr
from app.services.ocr import DocumentUnreadableError, extract_text_isolated


def _pdf(text="Invoice Number: INV-1\nTotal: 1,180.00"):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    y = 800
    for line in text.splitlines() * 3:
        c.drawString(50, y, line)
        y -= 16
    c.save()
    return buf.getvalue()


def test_extraction_runs_in_a_child_process_and_returns_text():
    result = extract_text_isolated(_pdf(), "inv.pdf", "application/pdf", timeout_seconds=60)
    assert result.method == "pdf_text" and "INV-1" in result.text


def test_slow_file_is_stopped_with_a_clear_message(monkeypatch):
    def too_slow(*a, **k):
        raise subprocess.TimeoutExpired(cmd="extract", timeout=120)
    monkeypatch.setattr(ocr.subprocess, "run", too_slow)
    with pytest.raises(DocumentUnreadableError, match="within 120 seconds"):
        extract_text_isolated(b"%PDF-1.4", "big.pdf", "application/pdf", timeout_seconds=120)


def test_crashing_parser_becomes_a_clear_message(monkeypatch):
    monkeypatch.setattr(ocr.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=1, stdout=b"", stderr=b"PDFSyntaxError: bad xref"))
    with pytest.raises(DocumentUnreadableError, match="damaged or incomplete"):
        extract_text_isolated(b"%PDF-1.4 junk", "bad.pdf", "application/pdf", timeout_seconds=10)


def _doc():
    return SimpleNamespace(id="d1", status="processing", minio_path="documents/d1/x.pdf", original_filename="x.pdf",
                           uploaded_by="u@x", processing_attempts=1, error_message=None, updated_at=None)


def _db(doc):
    db = AsyncMock()
    db.get.return_value = doc
    db.add = MagicMock()
    return db


@pytest.mark.asyncio
async def test_unreadable_file_fails_with_its_message():
    doc = _doc()
    with patch.object(document_service.storage, "download_bytes", AsyncMock(return_value=b"%PDF")), \
         patch.object(document_service.pipeline, "parsing_agent",
                      AsyncMock(side_effect=DocumentUnreadableError("This file couldn't be read"))), \
         patch.object(document_service, "write_audit_log", AsyncMock()) as audit:
        await document_service.process_document(_db(doc), None, "d1")
    assert doc.status == "failed" and doc.error_message == "This file couldn't be read"
    assert audit.call_args.kwargs["action"] == "failed"


@pytest.mark.asyncio
async def test_infrastructure_error_is_retried_not_failed():
    # Before: MinIO down for a moment = document permanently "failed".
    doc = _doc()
    with patch.object(document_service.storage, "download_bytes", AsyncMock(side_effect=ConnectionError("minio down"))):
        await document_service.process_document(_db(doc), None, "d1")
    assert doc.status == "pending"
    assert "retrying" in doc.error_message


@pytest.mark.asyncio
async def test_blank_pdf_fails_instead_of_becoming_an_invoice(monkeypatch):
    # Before: a blank page became an "invoice" from "Unknown Vendor".
    from app.services import extraction_router
    monkeypatch.setattr(extraction_router, "extract_text_isolated",
                        lambda *a: ocr.ExtractionResult(text="  \n ", method="pdf_text", file_type="pdf", text_quality=0.0))
    with pytest.raises(DocumentUnreadableError, match="couldn't find any text"):
        await extraction_router.route_extraction(AsyncMock(add=MagicMock()), "d1", b"%PDF", "blank.pdf", "application/pdf")


@pytest.mark.asyncio
async def test_no_vendor_name_means_no_vendor_not_unknown_vendor():
    from app.services import pipeline
    env = {"document_id": "d1", "document_type": "invoice", "extracted_fields": {"vendor_name_raw": "", "total": 10.0},
           "_agent_trail": []}
    with patch.object(pipeline, "find_or_create_vendor", AsyncMock()) as find:
        out = await pipeline.vendor_matching_agent(AsyncMock(), AsyncMock(), env, "u@x")
    find.assert_not_called()
    assert out["vendor_id"] is None and out["needs_review_forced"] is True


def test_blank_pdf_skips_ocr(monkeypatch):
    docling = MagicMock()
    monkeypatch.setattr(ocr, "_text_from_pdf_docling", docling)
    buf = io.BytesIO(); c = canvas.Canvas(buf, pagesize=A4); c.showPage(); c.save()
    result = ocr.extract_text(buf.getvalue(), "blank.pdf", "application/pdf")
    assert result.text == "" and docling.call_count == 0


@pytest.mark.asyncio
async def test_duplicate_check_is_serialised_per_vendor():
    # Two copies processed at once must not both miss each other.
    from app.services import pipeline
    db = AsyncMock()
    env = {"document_id": "d1", "document_type": "invoice", "vendor_id": "v1",
           "extracted_fields": {"total": 10.0}, "_agent_trail": []}
    with patch.object(pipeline, "check_duplicate_invoice",
                      AsyncMock(return_value=SimpleNamespace(is_duplicate=False, duplicate_of_document_id=None, reason=None))):
        await pipeline.duplicate_detection_agent(db, env)
    first_sql = str(db.execute.call_args_list[0].args[0])
    assert "pg_advisory_xact_lock" in first_sql
    assert db.execute.call_args_list[0].args[1] == {"k": "duplicate-check:v1"}
