"""Tests for Prompt 11 Section 4: Multi-file & folder upload, batch tracking, cancellation, retry, and CSV reporting."""
import io
import os
import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

from app.api import batches, documents
from app.database import get_db
from app.models import Document, DocumentBatch, DocumentBatchFile
from app.services.upload_service import (
    MAX_PDF_PAGES,
    InvalidUploadError,
    validate_upload,
    sniff_file_type,
)
from shared.auth import get_current_user
from shared.auth.middleware import CurrentUser


# =====================================================================
# 5.3 MULTI-FILE UPLOAD & BATCH TESTS
# =====================================================================
class TestUploadValidationLimits:
    def test_pdf_page_limit_enforced(self):
        # 100 pages -> valid
        valid_pdf = b"%PDF-1.4\n" + (b"/Type /Page\n" * 100) + b"%%EOF"
        assert validate_upload(valid_pdf, "doc.pdf") == "pdf"

        # 101 pages -> raises InvalidUploadError
        large_pdf = b"%PDF-1.4\n" + (b"/Type /Page\n" * 101) + b"%%EOF"
        with pytest.raises(InvalidUploadError) as exc_info:
            validate_upload(large_pdf, "large.pdf")
        assert f"max {MAX_PDF_PAGES}" in str(exc_info.value)

    def test_magic_byte_mismatch_rejected(self):
        # PNG bytes with .pdf extension
        png_bytes = b"\x89PNG\r\n\x1a\n"
        with pytest.raises(InvalidUploadError) as exc_info:
            validate_upload(png_bytes, "fraud.pdf")
        assert "file content is IMAGE but the name says .pdf" in str(exc_info.value)

    def test_tiff_support(self):
        # Little-endian TIFF header II\x2a\x00
        tiff_bytes = b"II\x2a\x00"
        assert sniff_file_type(tiff_bytes) == "image"

        # Big-endian TIFF header MM\x00\x2a
        tiff_be_bytes = b"MM\x00\x2a"
        assert sniff_file_type(tiff_be_bytes) == "image"


class TestBatchEndpoints:
    @pytest.fixture
    def test_app(self):
        app = FastAPI()
        app.state.kafka_producer = AsyncMock()
        app.include_router(batches.router, prefix="/documents")
        app.include_router(documents.router, prefix="/documents")
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            id="u1", email="uploader@example.com", role="requester"
        )
        return app

    def test_batch_creation_and_relative_paths(self, test_app):
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.flush = AsyncMock()

        test_app.dependency_overrides[get_db] = lambda: mock_db

        with TestClient(test_app) as client:
            payload = {
                "total_files": 2,
                "files": [
                    {
                        "client_file_id": "f-1",
                        "client_relative_path": "finance/invoices/inv1.pdf",
                        "filename": "inv1.pdf",
                        "file_size_bytes": 1024,
                    },
                    {
                        "client_file_id": "f-2",
                        "client_relative_path": "finance/contracts/agree.pdf",
                        "filename": "agree.pdf",
                        "file_size_bytes": 2048,
                    },
                ],
            }
            resp = client.post("/documents/batches", json=payload)
            assert resp.status_code == 201
            data = resp.json()["data"]
            assert "batch_id" in data
            assert data["total_files"] == 2
            assert data["status"] == "in_progress"
            assert mock_db.add.call_count >= 3

    def test_batch_cancellation(self, test_app):
        batch_id = "test-batch-cancel"
        mock_batch = SimpleNamespace(
            id=batch_id,
            user_id="uploader@example.com",
            status="in_progress",
            total_files=2,
            processed_files=0,
            failed_files=0,
            cancelled_files=0,
            completed_at=None,
            created_at=datetime.now(timezone.utc),
        )

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=mock_batch)
        mock_exec_result = MagicMock()
        mock_exec_result.rowcount = 2
        mock_db.execute = AsyncMock(return_value=mock_exec_result)
        mock_db.commit = AsyncMock()
        test_app.dependency_overrides[get_db] = lambda: mock_db

        with TestClient(test_app) as client:
            resp = client.post(f"/documents/batches/{batch_id}/cancel")
            assert resp.status_code == 200
            data = resp.json()["data"]
            assert data["batch_id"] == batch_id
            assert data["status"] == "cancelled"
            assert data["cancelled_files"] == 2

    def test_batch_retry_failed(self, test_app):
        batch_id = "test-batch-retry"
        mock_batch = SimpleNamespace(
            id=batch_id,
            user_id="uploader@example.com",
            status="failed",
            total_files=2,
            processed_files=1,
            failed_files=1,
            cancelled_files=0,
            completed_at=None,
            created_at=datetime.now(timezone.utc),
        )

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=mock_batch)
        mock_exec_result = MagicMock()
        mock_exec_result.rowcount = 1
        mock_db.execute = AsyncMock(return_value=mock_exec_result)
        mock_db.commit = AsyncMock()
        test_app.dependency_overrides[get_db] = lambda: mock_db

        with TestClient(test_app) as client:
            resp = client.post(f"/documents/batches/{batch_id}/retry-failed")
            assert resp.status_code == 200
            data = resp.json()["data"]
            assert data["batch_id"] == batch_id
            assert data["status"] == "in_progress"
            assert data["retried_files"] == 1
            assert mock_batch.failed_files == 0

    def test_batch_csv_report(self, test_app):
        batch_id = "test-batch-report"
        mock_batch = SimpleNamespace(
            id=batch_id,
            user_id="uploader@example.com",
            status="completed",
            total_files=1,
            processed_files=1,
            failed_files=0,
            cancelled_files=0,
            created_at=datetime.now(timezone.utc),
        )
        mock_file = SimpleNamespace(
            id="bf-1",
            batch_id=batch_id,
            client_file_id="cf-1",
            client_relative_path="docs/sample.pdf",
            filename="sample.pdf",
            file_size_bytes=4096,
            status="processed",
            sha256_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            document_id="doc-12345",
            error_code=None,
            error_detail=None,
            retry_count=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=mock_batch)

        async def mock_execute(stmt, params=None):
            m_res = MagicMock()
            m_res.scalars.return_value.all.return_value = [mock_file]
            return m_res

        mock_db.execute = AsyncMock(side_effect=mock_execute)
        test_app.dependency_overrides[get_db] = lambda: mock_db

        with TestClient(test_app) as client:
            resp = client.get(f"/documents/batches/{batch_id}/report.csv")
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/csv")
            csv_content = resp.text
            assert "client_relative_path" in csv_content
            assert "docs/sample.pdf" in csv_content
            assert "doc-12345" in csv_content


class TestUploadDeduplicationAndRateLimit:
    @pytest.fixture
    def test_app(self):
        app = FastAPI()
        app.state.kafka_producer = AsyncMock()
        app.include_router(documents.router, prefix="/documents")
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            id="u1", email="uploader@example.com", role="requester"
        )
        return app

    def test_duplicate_upload_detection(self, test_app):
        # When a file with same SHA-256 exists, store_and_record_upload returns is_likely_duplicate=True
        mock_doc = SimpleNamespace(
            id="doc-dup-2",
            status="classified",
            sha256_hash="abc123sha256",
            is_likely_duplicate=True,
            duplicate_of_document_id="doc-original-1",
            content_type="application/pdf",
            total_pages=1,
            original_filename="sample.pdf",
            storage_key="docs/sample.pdf",
            uploader_id="u1",
            total=None,
            total_inr=None,
            confidence_score=None,
            needs_review=False,
            created_at=datetime.now(timezone.utc),
        )

        mock_db = AsyncMock()
        mock_db.scalar = AsyncMock(return_value=None)
        mock_db.commit = AsyncMock()
        test_app.dependency_overrides[get_db] = lambda: mock_db

        with patch.object(documents, "scan_upload", AsyncMock()), \
             patch.object(documents, "store_and_record_upload", AsyncMock(return_value=mock_doc)):
            with TestClient(test_app) as client:
                resp = client.post(
                    "/documents/upload",
                    files={"file": ("sample.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
                )
                assert resp.status_code == 201
                data = resp.json()["data"]
                assert data["is_likely_duplicate"] is True
                assert data["duplicate_of_document_id"] == "doc-original-1"
                assert data["sha256_hash"] == "abc123sha256"

    def test_upload_rate_limiting(self, test_app):
        # Set redis mock directly on test_app.state.redis
        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=61)
        mock_redis.expire = AsyncMock()

        test_app.state.redis = mock_redis
        test_app.dependency_overrides[get_db] = lambda: AsyncMock()

        with TestClient(test_app) as client:
            resp = client.post(
                "/documents/upload",
                files={"file": ("sample.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
            )
            assert resp.status_code == 429
            assert "rate limit exceeded" in resp.json()["detail"].lower()
