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

    @pytest.fixture
    def documenso(self, monkeypatch):
        """A stand-in Documenso Envelope API; records each call."""
        monkeypatch.setattr(settings, "documenso_api_url", "http://documenso.test")
        monkeypatch.setattr(settings, "documenso_api_token", "api_tok")
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            path = request.url.path
            if path == "/api/v2/envelope/create":
                return httpx.Response(200, json={"id": "envelope_42"})
            if path == "/api/v2/envelope/distribute":
                return httpx.Response(200, json={"success": True, "recipients": [
                    {"id": 8, "email": "priya@vendor.test", "token": "tok-vendor"},
                    {"id": 7, "email": "cfo@acme.test", "token": "tok-company"},
                ]})
            if path == "/api/v2/envelope/envelope_42":
                return httpx.Response(200, json={"envelopeItems": [{"id": "item_1"}]})
            if path == "/api/v2/envelope/item/item_1/download":
                assert request.url.params["version"] == "signed"
                return httpx.Response(200, content=b"%PDF-sealed")
            return httpx.Response(404)

        real_client = httpx.AsyncClient
        monkeypatch.setattr(
            esign_client.httpx, "AsyncClient",
            lambda *a, **kw: real_client(*a, transport=httpx.MockTransport(handler), **kw),
        )
        return calls

    @pytest.mark.asyncio
    async def test_envelope_with_two_signers_in_order(self, documenso):
        import json as _json
        field = {"page": 2, "positionX": 9.0, "positionY": 40.0, "width": 36.0, "height": 4.0}
        ref, recipients = await esign_client.documenso_send_envelope("c-1", "SaaS", b"%PDF", [
            esign_client.EnvelopeSigner("company", "CFO", "cfo@acme.test", field),
            esign_client.EnvelopeSigner("vendor", "Priya", "priya@vendor.test", {**field, "positionX": 55.0}),
        ])
        assert ref == "documenso-env-envelope_42"
        assert [(r.party, r.recipient_id, r.token) for r in recipients] == [
            ("company", "7", "tok-company"), ("vendor", "8", "tok-vendor")]
        create, distribute = documenso[0], documenso[1]
        assert create.headers["authorization"] == "api_tok"
        body = create.content.decode("latin-1")
        payload = _json.loads(body[body.index("{"):body.rindex("}") + 1].split("\r\n--")[0])
        assert payload["externalId"] == "c-1"
        # Sequential, and Documenso emails nobody: signing happens on the platform's pages.
        assert payload["meta"]["signingOrder"] == "SEQUENTIAL" and payload["meta"]["distributionMethod"] == "NONE"
        assert [(r["email"], r["signingOrder"], r["fields"][0]["positionX"]) for r in payload["recipients"]] == [
            ("cfo@acme.test", 1, 9.0), ("priya@vendor.test", 2, 55.0)]
        assert _json.loads(distribute.content)["meta"]["distributionMethod"] == "NONE"

    @pytest.mark.asyncio
    async def test_signed_copy_is_documensos_sealed_pdf(self, documenso):
        assert await esign_client.download_signed_pdf("documenso-env-envelope_42") == b"%PDF-sealed"

    @pytest.mark.asyncio
    async def test_documenso_error_is_surfaced(self, monkeypatch):
        monkeypatch.setattr(settings, "documenso_api_url", "http://documenso.test")
        monkeypatch.setattr(settings, "documenso_api_token", "bad")
        real_client = httpx.AsyncClient
        monkeypatch.setattr(
            esign_client.httpx, "AsyncClient",
            lambda *a, **kw: real_client(*a, transport=httpx.MockTransport(lambda r: httpx.Response(401, text="Unauthorized")), **kw),
        )
        with pytest.raises(esign_client.EsignProviderError, match="401"):
            await esign_client.documenso_send_envelope("c-1", "x", b"%PDF", [])


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
    async def test_signing_events_go_to_the_signing_service(self, monkeypatch):
        monkeypatch.setattr(settings, "documenso_webhook_secret", "whsec")
        from app.services import signing_service
        handle = AsyncMock(return_value=MagicMock(id="c-1", status="signed"))
        monkeypatch.setattr(signing_service, "handle_documenso_event", handle)
        for event in ("DOCUMENT_RECIPIENT_COMPLETED", "DOCUMENT_COMPLETED", "DOCUMENT_REJECTED"):
            await webhook_service.handle_documenso_webhook(AsyncMock(), None, {**self.COMPLETED, "event": event}, "whsec")
        assert handle.await_count == 3


class TestEsignTracking:
    """Control Panel → E-signatures: one row per contract with its status
    label and in-app PDF links (app/api/contracts.py esign_row)."""

    def test_pending_contract_links_only_the_unsigned_pdf(self):
        from app.api.contracts import esign_row
        row = esign_row({"contract_id": "c-1", "status": "pending_signature", "provider": "builtin"})
        assert row["status_label"] == "Pending E-Signature"
        assert row["unsigned_pdf"] == "/api/contracts/c-1/document"
        assert row["signed_pdf"] is None and row["certificate"] is None

    def test_signed_contract_links_the_signed_pdf_and_certificate(self):
        from app.api.contracts import esign_row
        row = esign_row({"contract_id": "c-1", "status": "signed", "provider": "builtin"})
        assert row["status_label"] == "E-Signature Complete"
        assert row["signed_pdf"] == "/api/contracts/c-1/signed-document"
        assert row["certificate"] == "/api/contracts/c-1/signature-certificate"

    @pytest.mark.parametrize("role", ["requester", "approver", "finance"])
    def test_admin_only(self, role):
        from app.api import contracts
        app = FastAPI()
        app.include_router(contracts.router, prefix="/contracts")
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(id="u", email="x@acme.test", role=role)
        app.dependency_overrides[get_db] = lambda: MagicMock()
        assert TestClient(app).get("/contracts/esign/documents").status_code == 403


class TestContractOnlyAfterFinalApproval:
    """approval.decided arrives per level: a manager's approval of a
    manager + finance request must not generate the contract yet
    (readmeforme Appendix A, "Known gap")."""

    @pytest.mark.parametrize("level,chain,final", [
        ("level_1_dept_manager", ["dept_manager", "finance_head"], False),
        ("level_2_finance_head", ["dept_manager", "finance_head"], True),
        ("level_1_dept_manager", ["dept_manager"], True),
        ("auto", [], True),
        (None, None, True),
    ])
    def test_is_final_approval(self, level, chain, final):
        from app.kafka.consumer import is_final_approval
        assert is_final_approval(level, chain) is final

    def test_first_level_approval_generates_nothing(self):
        import asyncio
        from app.kafka import consumer
        session = AsyncMock()
        session.__aenter__.return_value = session
        session.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: ["dept_manager", "finance_head"])
        generate = AsyncMock()
        with patch.object(consumer, "async_session_factory", return_value=session), \
             patch.object(consumer, "generate_contract_for_request", generate):
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(consumer._handle_approval_decided(
                    SimpleNamespace(state=SimpleNamespace(kafka_producer=None)),
                    {"request_id": "r-1", "decision": "approved", "decision_level": "level_1_dept_manager"}))
            finally:
                loop.close()
        generate.assert_not_awaited()
