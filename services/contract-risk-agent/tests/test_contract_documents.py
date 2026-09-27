"""Contract PDF generation, signed-copy download, and the Documenso
client/webhook."""
import os
import sys
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.database import get_db
from app.services import contract_service, esign_client, webhook_service
from app.services.contract_pdf import AuditEntry, ContractPdfInput, _split_text, render_contract_pdf, text_sha256
from shared.auth import get_current_user
from shared.auth.middleware import CurrentUser

CONTRACT_TEXT = """SAAS SUBSCRIPTION AGREEMENT
Contract ID: c-1

1. SUBSCRIPTION
   Subscribed services:
   - Slack Business+ x50 @ 700 INR

2. SERVICE LEVEL
   Provider shall maintain 99.9% uptime.

3. SIGNATURES
   Subscriber: ______________________     Provider: ______________________
   Date:       ______________________     Date:      ______________________
"""


def _pdf_input(**overrides) -> ContractPdfInput:
    base = dict(
        contract_id=str(uuid.uuid4()), contract_text=CONTRACT_TEXT, status="draft", version=1,
        template="saas_subscription", vendor_name="Slack Technologies",
        generated_at=datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc),
    )
    base.update(overrides)
    return ContractPdfInput(**base)


class TestContractPdf:
    def test_title_split_and_template_signature_lines_dropped(self):
        title, body = _split_text(CONTRACT_TEXT)
        assert title == "SAAS SUBSCRIPTION AGREEMENT"
        joined = "\n".join(body)
        assert "2. SERVICE LEVEL" in joined
        assert "SIGNATURES" not in joined and "______" not in joined

    def test_working_copy_is_a_single_page_pdf(self):
        pdf = render_contract_pdf(_pdf_input())
        assert pdf.startswith(b"%PDF")
        assert esign_client._pdf_page_count(pdf) == 1

    def test_signed_copy_adds_certificate_page(self):
        signed = _pdf_input(
            status="signed", signed_by="cfo@acme.test",
            signed_at=datetime(2026, 9, 21, 9, 30, tzinfo=timezone.utc),
            esign_provider_ref="documenso-ref-abc",
            audit_trail=[AuditEntry(at=datetime(2026, 9, 20, tzinfo=timezone.utc), action="generated")],
        )
        pdf = render_contract_pdf(signed, include_certificate=True)
        assert esign_client._pdf_page_count(pdf) == 2

    def test_text_hash_is_stable(self):
        assert text_sha256(CONTRACT_TEXT) == text_sha256(CONTRACT_TEXT)
        assert text_sha256(CONTRACT_TEXT) != text_sha256(CONTRACT_TEXT + " ")


class TestSignedDocument:
    @pytest.mark.asyncio
    async def test_unsigned_contract_has_no_signed_copy(self):
        with pytest.raises(contract_service.ContractNotSignedError):
            await contract_service.render_signed_document(AsyncMock(), SimpleNamespace(id="c-1", status="pending_signature"))

    @pytest.fixture
    def client(self):
        from app.api import contracts
        app = FastAPI()
        app.state.kafka_producer = AsyncMock()
        app.include_router(contracts.router, prefix="/contracts")
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(id="u", email="a@b.com", role="finance")
        app.dependency_overrides[get_db] = lambda: AsyncMock()
        with TestClient(app) as c:
            yield c

    def test_download_before_signing_is_409(self, client):
        contract = SimpleNamespace(id="c-1", status="draft", version=1)
        with patch.object(contract_service, "get_contract", AsyncMock(return_value=contract)):
            resp = client.get("/contracts/c-1/signed-document")
        assert resp.status_code == 409

    def test_download_after_signing_returns_pdf(self, client):
        contract = SimpleNamespace(id="c1234567-aaaa", status="signed", version=2)
        with patch.object(contract_service, "get_contract", AsyncMock(return_value=contract)), \
             patch.object(contract_service, "render_signed_document", AsyncMock(return_value=b"%PDF-1.4 signed")):
            resp = client.get("/contracts/c1234567-aaaa/signed-document")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert 'filename="contract-c1234567-v2-signed.pdf"' in resp.headers["content-disposition"]
        assert resp.content == b"%PDF-1.4 signed"

    def test_working_copy_download(self, client):
        contract = SimpleNamespace(id="c1234567-aaaa", status="draft", version=1)
        with patch.object(contract_service, "get_contract", AsyncMock(return_value=contract)), \
             patch.object(contract_service, "render_document", AsyncMock(return_value=b"%PDF-draft")):
            resp = client.get("/contracts/c1234567-aaaa/document")
        assert resp.status_code == 200
        assert 'filename="contract-c1234567-v1.pdf"' in resp.headers["content-disposition"]


class TestEsignClient:
    @pytest.mark.asyncio
    async def test_simulated_when_documenso_not_configured(self, monkeypatch):
        monkeypatch.setattr(settings, "documenso_api_url", None)
        ref = await esign_client.request_signature("c-1", "s@acme.test", provider="documenso")
        assert ref.startswith("documenso-ref-")
        assert await esign_client.download_signed_pdf(ref) is None

    @pytest.mark.asyncio
    async def test_documenso_flow(self, monkeypatch):
        monkeypatch.setattr(settings, "documenso_api_url", "http://documenso.test")
        monkeypatch.setattr(settings, "documenso_api_token", "api_tok")
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append((request.method, str(request.url), request.headers.get("authorization")))
            path = request.url.path
            if path == "/api/v1/documents" and request.method == "POST":
                return httpx.Response(200, json={
                    "documentId": 42, "uploadUrl": "http://storage.test/upload/42",
                    "recipients": [{"recipientId": 7, "email": "s@acme.test"}],
                })
            if path == "/upload/42":
                assert request.headers["content-type"] == "application/pdf"
                return httpx.Response(200)
            if path == "/api/v1/documents/42/fields":
                return httpx.Response(200, json={})
            if path == "/api/v1/documents/42/send":
                return httpx.Response(200, json={})
            if path == "/api/v1/documents/42/download":
                return httpx.Response(200, json={"downloadUrl": "http://storage.test/signed/42"})
            if path == "/signed/42":
                return httpx.Response(200, content=b"%PDF-sealed")
            return httpx.Response(404)

        real_client = httpx.AsyncClient
        monkeypatch.setattr(
            esign_client.httpx, "AsyncClient",
            lambda *a, **kw: real_client(*a, transport=httpx.MockTransport(handler), **kw),
        )

        pdf = render_contract_pdf(_pdf_input())
        ref = await esign_client.request_signature("c-1", "s@acme.test", pdf=pdf, title="SaaS")
        assert ref == "documenso-doc-42"
        # API calls carry the token; the pre-signed storage upload does not.
        assert calls[0][2] == "api_tok"
        assert calls[1][1] == "http://storage.test/upload/42" and calls[1][2] is None
        assert [c[1].rsplit("/", 1)[-1] for c in calls[2:]] == ["fields", "send"]

        assert await esign_client.download_signed_pdf(ref) == b"%PDF-sealed"

    @pytest.mark.asyncio
    async def test_documenso_error_is_surfaced(self, monkeypatch):
        monkeypatch.setattr(settings, "documenso_api_url", "http://documenso.test")
        monkeypatch.setattr(settings, "documenso_api_token", "bad")
        real_client = httpx.AsyncClient
        monkeypatch.setattr(
            esign_client.httpx, "AsyncClient",
            lambda *a, **kw: real_client(*a, transport=httpx.MockTransport(lambda r: httpx.Response(401, text="Unauthorized")), **kw),
        )
        with pytest.raises(esign_client.EsignProviderError):
            await esign_client.request_signature("c-1", "s@acme.test", pdf=b"%PDF", title="x")


class TestDocumensoWebhook:
    COMPLETED = {
        "event": "DOCUMENT_COMPLETED",
        "payload": {
            "id": 42, "externalId": "c-1", "status": "COMPLETED", "completedAt": "2026-09-21T09:30:00.000Z",
            "recipients": [{"email": "cfo@acme.test", "role": "SIGNER", "signedAt": "2026-09-21T09:29:00.000Z"}],
        },
    }

    @pytest.mark.asyncio
    async def test_wrong_or_missing_secret_rejected(self, monkeypatch):
        monkeypatch.setattr(settings, "documenso_webhook_secret", "whsec")
        for secret in (None, "nope"):
            with pytest.raises(webhook_service.WebhookSignatureError):
                await webhook_service.handle_documenso_webhook(AsyncMock(), None, self.COMPLETED, secret)

    @pytest.mark.asyncio
    async def test_unconfigured_secret_rejects_everything(self, monkeypatch):
        monkeypatch.setattr(settings, "documenso_webhook_secret", None)
        with pytest.raises(webhook_service.WebhookSignatureError):
            await webhook_service.handle_documenso_webhook(AsyncMock(), None, self.COMPLETED, "")

    @pytest.mark.asyncio
    async def test_other_events_ignored(self, monkeypatch):
        monkeypatch.setattr(settings, "documenso_webhook_secret", "whsec")
        body = {"event": "DOCUMENT_OPENED", "payload": {"id": 42, "externalId": "c-1"}}
        assert await webhook_service.handle_documenso_webhook(AsyncMock(), None, body, "whsec") is None

    @pytest.mark.asyncio
    async def test_completed_marks_contract_signed(self, monkeypatch):
        monkeypatch.setattr(settings, "documenso_webhook_secret", "whsec")
        mark = AsyncMock(return_value=MagicMock(id="c-1", status="signed"))
        monkeypatch.setattr(webhook_service, "mark_contract_signed", mark)
        await webhook_service.handle_documenso_webhook(AsyncMock(), None, self.COMPLETED, "whsec")
        kwargs = mark.call_args.kwargs
        assert kwargs["contract_id"] == "c-1"
        assert kwargs["signed_by"] == "cfo@acme.test"
        assert kwargs["signed_at"] == datetime(2026, 9, 21, 9, 30, tzinfo=timezone.utc)
        assert kwargs["provider_event_id"] == "documenso-42-completed"
