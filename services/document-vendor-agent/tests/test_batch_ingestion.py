"""Multi-document ingestion: POST /documents/upload/batch, and the worker
processing several document.ingested events at once."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import documents
from app.config import settings
from app.database import get_db
from app.kafka import consumer as consumer_mod
from app.services.upload_service import MalwareDetectedError
from shared.auth import get_current_user
from shared.auth.middleware import CurrentUser


@pytest.fixture
def client():
    app = FastAPI()
    app.state.kafka_producer = AsyncMock()
    app.include_router(documents.router, prefix="/documents")
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id="u1", email="req@acme.test", role="requester")
    app.dependency_overrides[get_db] = lambda: AsyncMock()
    with TestClient(app) as c:
        yield c


def _stored(doc_id):
    return SimpleNamespace(id=doc_id, status="pending")


class TestBatchUpload:
    def test_each_file_gets_its_own_result(self, client):
        async def scan(data, db, filename):
            if filename == "bad.pdf":
                raise MalwareDetectedError("Eicar-Test-Signature")

        store = AsyncMock(side_effect=[_stored("doc-1"), _stored("doc-2")])
        with patch.object(documents, "scan_upload", side_effect=scan), \
             patch.object(documents, "store_and_record_upload", store):
            resp = client.post("/documents/upload/batch", files=[
                ("files", ("a.pdf", b"%PDF-a", "application/pdf")),
                ("files", ("empty.pdf", b"", "application/pdf")),
                ("files", ("bad.pdf", b"%PDF-bad", "application/pdf")),
                ("files", ("b.png", b"\x89PNG", "image/png")),
            ])

        assert resp.status_code == 201
        body = resp.json()
        assert body["meta"] == {"accepted": 2, "rejected": 2}
        results = body["data"]
        assert [r["filename"] for r in results] == ["a.pdf", "empty.pdf", "bad.pdf", "b.png"]
        assert results[0]["document_id"] == "doc-1"
        assert results[1]["error"] == "file is empty"
        assert "malware" in results[2]["error"]
        assert results[3]["document_id"] == "doc-2"
        # Uploader identity comes from the JWT, not a form field.
        assert all(call.args[5] == "req@acme.test" for call in store.call_args_list)

    def test_all_rejected_is_422(self, client):
        with patch.object(documents, "scan_upload", AsyncMock()), \
             patch.object(documents, "store_and_record_upload", AsyncMock()) as store:
            resp = client.post("/documents/upload/batch", files=[("files", ("e.pdf", b"", "application/pdf"))])
        assert resp.status_code == 422
        assert resp.json()["meta"]["accepted"] == 0
        store.assert_not_called()

    def test_too_many_files(self, client):
        files = [("files", (f"{i}.pdf", b"%PDF", "application/pdf")) for i in range(settings.max_batch_files + 1)]
        resp = client.post("/documents/upload/batch", files=files)
        assert resp.status_code == 413


class _FakeMsg:
    def __init__(self, n):
        self.topic = "document.ingested"
        self.value = {"event_type": "document.ingested", "payload": {"document_id": f"doc-{n}"}}


class _FakeConsumer:
    def __init__(self, *args, **kwargs):
        self.messages = [_FakeMsg(i) for i in range(6)]

    async def start(self):
        pass

    async def stop(self):
        pass

    def __aiter__(self):
        return self._iter()

    async def _iter(self):
        for m in self.messages:
            yield m


class TestConcurrentWorker:
    @pytest.mark.asyncio
    async def test_documents_run_in_parallel_up_to_the_limit(self, monkeypatch):
        running = 0
        peak = 0
        done = []

        async def handle(_producer, payload):
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.05)
            running -= 1
            done.append(payload["document_id"])

        monkeypatch.setattr(settings, "worker_concurrency", 3)
        monkeypatch.setattr(consumer_mod, "AIOKafkaConsumer", _FakeConsumer)
        monkeypatch.setattr(consumer_mod, "ensure_ingest_partitions", AsyncMock())
        monkeypatch.setattr(consumer_mod, "requeue_stranded_documents", AsyncMock(return_value=0))
        monkeypatch.setattr(consumer_mod, "_handle_document_ingested", handle)

        await consumer_mod.start_consumer(AsyncMock())

        # Every document finished (the consumer drains in-flight work on
        # stop), several ran at once, and never more than the limit.
        assert sorted(done) == [f"doc-{i}" for i in range(6)]
        assert peak == 3

    @pytest.mark.asyncio
    async def test_claim_is_atomic_per_document(self):
        db = AsyncMock()
        db.execute.return_value = MagicMock(rowcount=1)
        assert await consumer_mod.claim_document(db, "doc-1") is True
        db.execute.return_value = MagicMock(rowcount=0)
        assert await consumer_mod.claim_document(db, "doc-1") is False

    @pytest.mark.asyncio
    async def test_already_claimed_document_is_not_reprocessed(self, monkeypatch):
        process = AsyncMock()
        monkeypatch.setattr(consumer_mod, "claim_document", AsyncMock(return_value=False))
        monkeypatch.setattr(consumer_mod, "process_document", process)
        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=AsyncMock())
        session.__aexit__ = AsyncMock(return_value=False)
        monkeypatch.setattr(consumer_mod, "async_session_factory", lambda: session)

        await consumer_mod._handle_document_ingested(AsyncMock(), {"document_id": "doc-1"})
        process.assert_not_called()
