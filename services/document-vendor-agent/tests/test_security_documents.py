"""Security audit (Sep 26): document access, uploader identity, upload
validation. Each test fails against the code before the fix."""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import documents, vendors
from app.database import get_db
from app.services import document_service
from app.services.upload_service import InvalidUploadError, safe_filename, validate_upload
from shared.auth import get_current_user
from shared.auth.middleware import CurrentUser

PDF = b"%PDF-1.4\n1 0 obj << /Type /Page >> endobj\n%%EOF"


def _doc(uploaded_by="alice@acme.test", **extracted):
    return SimpleNamespace(
        id="d1", status="classified", document_type="invoice", vendor_id="v1", vendor_name_raw="Dell",
        extracted={"total": 100.0, "bank_account_number": "123456789012", "routing_code": "HDFC0001234", **extracted},
        confidence={}, overall_confidence=0.9, needs_review=False, is_likely_duplicate=False,
        duplicate_of_document_id=None, file_type="pdf", original_filename="inv.pdf", uploaded_by=uploaded_by,
        uploaded_at=datetime.now(timezone.utc), reviewed_by=None, reviewed_at=None, error_message=None,
    )


def _client(role, email="alice@acme.test"):
    app = FastAPI()
    app.state.kafka_producer = AsyncMock()
    app.state.redis = None
    app.include_router(documents.router, prefix="/documents")
    app.include_router(vendors.router, prefix="/vendors")
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id="u-" + role, email=email, role=role)
    app.dependency_overrides[get_db] = lambda: AsyncMock()
    return TestClient(app)


class TestUploaderIdentity:
    def test_uploaded_by_form_field_is_ignored(self):
        # C1: a finance user could submit a bank change "as" a colleague and
        # then verify it themselves, defeating dual control.
        store = AsyncMock(return_value=SimpleNamespace(id="d1", status="pending"))
        with patch.object(documents, "scan_upload", AsyncMock()), patch.object(documents, "store_and_record_upload", store):
            r = _client("finance", "fin@acme.test").post(
                "/documents/upload",
                files={"file": ("inv.pdf", PDF, "application/pdf")},
                data={"uploaded_by": "colleague@acme.test"},
            )
        assert r.status_code == 201
        assert store.call_args.args[5] == "fin@acme.test"


class TestDocumentAccess:
    def test_requester_lists_only_own_documents(self):
        lister = AsyncMock(return_value=[])
        with patch.object(document_service, "list_all_documents", lister):
            _client("requester").get("/documents/")
        assert lister.call_args.kwargs["uploaded_by"] == "alice@acme.test"

    def test_staff_list_everything(self):
        lister = AsyncMock(return_value=[])
        with patch.object(document_service, "list_all_documents", lister):
            _client("approver", "appr@acme.test").get("/documents/")
        assert lister.call_args.kwargs["uploaded_by"] is None

    def test_requester_cannot_read_someone_elses_document(self):
        with patch.object(document_service, "get_document", AsyncMock(return_value=_doc(uploaded_by="bob@acme.test"))):
            assert _client("requester").get("/documents/d1").status_code == 404

    @pytest.mark.parametrize("role,expect_full", [("requester", False), ("approver", False), ("finance", True), ("admin", True)])
    def test_bank_details_masked_unless_finance(self, role, expect_full):
        with patch.object(document_service, "get_document", AsyncMock(return_value=_doc())):
            body = _client(role).get("/documents/d1").json()["data"]["extracted_fields"]
        if expect_full:
            assert body["bank_account_number"] == "123456789012"
        else:
            assert body["bank_account_number"] == "••••9012"
            assert body["routing_code"] == "••••1234"
        assert body["total"] == 100.0

    def test_requester_cannot_review_someone_elses_document(self):
        submit = AsyncMock()
        with patch.object(document_service, "get_document", AsyncMock(return_value=_doc(uploaded_by="bob@acme.test"))), \
             patch.object(document_service, "submit_review", submit):
            r = _client("requester").post("/documents/d1/review", json={"extracted_fields": {"total": 1}})
        assert r.status_code == 404
        submit.assert_not_called()

    def test_owner_can_review_own_document(self):
        submit = AsyncMock(return_value=_doc())
        with patch.object(document_service, "get_document", AsyncMock(return_value=_doc())), \
             patch.object(document_service, "submit_review", submit):
            r = _client("requester").post("/documents/d1/review", json={"extracted_fields": {"total": 1}})
        assert r.status_code == 200
        submit.assert_awaited_once()

    def test_review_cannot_change_bank_details(self):
        submit = AsyncMock(return_value=_doc())
        with patch.object(document_service, "get_document", AsyncMock(return_value=_doc())), \
             patch.object(document_service, "submit_review", submit):
            _client("approver", "appr@acme.test").post("/documents/d1/review", json={"extracted_fields": {
                "total": 5, "bank_account_number": "••••9012", "routing_code": "EVIL0000001",
                "payment_beneficiary_name": "Mallory"}})
        fields = submit.call_args.args[3].extracted_fields
        assert fields == {"total": 5}

    def test_payment_change_queue_is_finance_only(self):
        assert _client("requester").get("/vendors/payment-changes/pending").status_code == 403
        assert _client("approver").get("/vendors/v1/payment-changes").status_code == 403


class TestUploadValidation:
    @pytest.mark.parametrize("raw,expected", [
        ("../../other-doc/invoice.pdf", "invoice.pdf"),
        ("..\\\\..\\\\evil.pdf", "evil.pdf"),
        ("in\x00voice<script>.pdf", "in_voice_script_.pdf"),
        ("", "upload"),
        ("..", "upload"),
    ])
    def test_safe_filename(self, raw, expected):
        assert safe_filename(raw) == expected

    def test_type_comes_from_the_bytes(self):
        assert validate_upload(PDF, "inv.pdf") == "pdf"
        with pytest.raises(InvalidUploadError, match="unsupported"):
            validate_upload(b"MZ\x90\x00 an executable", "inv.pdf")
        with pytest.raises(InvalidUploadError, match="name says"):
            validate_upload(PDF, "photo.png")

    def test_pdf_page_bomb_rejected(self):
        bomb = b"%PDF-1.4\n" + b"<< /Type /Page >>\n" * 201
        with pytest.raises(InvalidUploadError, match="too many pages"):
            validate_upload(bomb, "big.pdf")

    def test_image_pixel_bomb_rejected(self):
        import io
        import struct
        import zlib
        # A valid PNG header claiming 20000 x 20000 pixels (400 MP).
        def chunk(t, d):
            return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
        png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 20000, 20000, 8, 2, 0, 0, 0)) + chunk(b"IEND", b"")
        with pytest.raises(InvalidUploadError, match="too large"):
            validate_upload(png, "scan.png")
