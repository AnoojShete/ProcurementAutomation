"""DocuSign client (app/services/docusign_client.py), its place in the e-sign
client, and the drop folder's one-time auto-send."""
import asyncio
import base64
import hashlib
import hmac
import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

from app.api import webhooks
from app.database import get_db
from app.services import contract_service, docusign_client, esign_client
from app.services.docusign_client import completion, envelope_definition, verify_connect_signature


def run(coro):
    """Own event loop, so the suite's other tests keep the default one."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture
def rsa_key():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    return key, pem


@pytest.fixture
def docusign_on(monkeypatch, rsa_key):
    s = docusign_client.settings
    monkeypatch.setattr(s, "docusign_integration_key", "ik-123")
    monkeypatch.setattr(s, "docusign_user_id", "user-456")
    monkeypatch.setattr(s, "docusign_account_id", "acct-789")
    # .env files can't hold multi-line values; "\n" escapes must work.
    monkeypatch.setattr(s, "docusign_private_key", rsa_key[1].replace("\n", "\\n"))
    monkeypatch.setattr(s, "docusign_connect_hmac_key", "connect-key")
    monkeypatch.setitem(docusign_client._token, "value", None)
    return s


class TestJwtGrant:
    def test_disabled_without_all_keys(self, monkeypatch):
        monkeypatch.setattr(docusign_client.settings, "docusign_integration_key", None)
        assert not docusign_client.docusign_enabled()

    def test_assertion_is_rs256_signed_for_the_configured_user(self, docusign_on, rsa_key):
        token = docusign_client.build_jwt_assertion(now=1_000_000)
        claims = jwt.decode(
            token, rsa_key[0].public_key(), algorithms=["RS256"], audience="account-d.docusign.com",
            options={"verify_exp": False, "verify_iat": False},
        )
        assert claims["iss"] == "ik-123" and claims["sub"] == "user-456"
        assert claims["scope"] == "signature impersonation"
        assert claims["exp"] - claims["iat"] == 3600

    def test_consent_link_names_the_app(self, docusign_on):
        url = docusign_client.consent_url()
        assert url.startswith("https://account-d.docusign.com/oauth/auth?")
        assert "client_id=ik-123" in url and "scope=signature+impersonation" in url


class TestEnvelope:
    def test_definition_sends_immediately_with_one_signer_on_the_company_line(self):
        env = envelope_definition("c-1", "signer@example.com", "Sam Signer", b"%PDF-1", "SaaS Agreement — Acme")
        assert env["status"] == "sent"  # DocuSign emails the signer now
        [signer] = env["recipients"]["signers"]
        assert signer["email"] == "signer@example.com" and signer["name"] == "Sam Signer"
        assert signer["tabs"]["signHereTabs"][0]["anchorString"] == "For the Company"
        assert base64.b64decode(env["documents"][0]["documentBase64"]) == b"%PDF-1"
        assert env["customFields"]["textCustomFields"][0] == {"name": "contract_id", "value": "c-1", "show": "false"}

    def test_completion_only_for_completed_envelopes(self):
        assert completion({"status": "sent"}) is None
        signed_by, signed_at = completion({
            "status": "completed", "completedDateTime": "2026-10-10T09:30:00.000Z",
            "recipients": {"signers": [{"email": "signer@example.com"}]},
        })
        assert signed_by == "signer@example.com" and signed_at.isoformat() == "2026-10-10T09:30:00+00:00"


class TestProviderRouting:
    def test_docusign_send_goes_to_docusign_when_configured(self, docusign_on, monkeypatch):
        send = AsyncMock(return_value="docusign-env-abc")
        monkeypatch.setattr(docusign_client, "send_envelope", send)
        ref = run(esign_client.request_signature(
            "c-1", "signer@example.com", provider="docusign", pdf=b"%PDF", title="T", signer_name="Sam",
        ))
        assert ref == "docusign-env-abc"
        send.assert_awaited_once_with("c-1", "signer@example.com", "Sam", b"%PDF", "T")

    def test_docusign_send_is_simulated_when_not_configured(self, monkeypatch):
        monkeypatch.setattr(docusign_client.settings, "docusign_integration_key", None)
        send = AsyncMock()
        monkeypatch.setattr(docusign_client, "send_envelope", send)
        ref = run(esign_client.request_signature("c-1", "s@example.com", provider="docusign", pdf=b"%PDF"))
        assert ref.startswith("docusign-ref-")
        send.assert_not_awaited()

    def test_live_envelope_completes_in_docusign_not_in_the_platform(self):
        assert esign_client.live_provider_ref("docusign-env-abc") == "DocuSign"
        assert esign_client.live_provider_ref("documenso-doc-1") == "Documenso"
        assert esign_client.live_provider_ref("docusign-ref-1234") is None  # simulated


class TestConnectWebhook:
    def _sign(self, body: bytes, key="connect-key"):
        return base64.b64encode(hmac.new(key.encode(), body, hashlib.sha256).digest()).decode()

    def test_hmac_matches_docusign_format(self, docusign_on):
        body = b'{"event":"envelope-completed"}'
        assert verify_connect_signature(body, [self._sign(body)])
        assert not verify_connect_signature(body, [self._sign(body, key="wrong")])
        assert not verify_connect_signature(body + b" ", [self._sign(body)])

    def test_endpoint_rejects_unsigned_and_reads_the_envelope_back(self, docusign_on, monkeypatch):
        app = FastAPI()
        app.state.kafka_producer = AsyncMock()
        app.include_router(webhooks.router, prefix="/webhooks")
        db = AsyncMock()
        db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value="c-1"))
        app.dependency_overrides[get_db] = lambda: db
        monkeypatch.setattr(docusign_client, "get_envelope", AsyncMock(return_value={
            "status": "completed", "completedDateTime": "2026-10-10T09:30:00Z",
            "recipients": {"signers": [{"email": "signer@example.com"}]},
        }))
        mark = AsyncMock(return_value=MagicMock(id="c-1", status="signed"))
        monkeypatch.setattr(webhooks.webhook_service, "mark_contract_signed", mark)
        body = json.dumps({"event": "envelope-completed", "data": {"envelopeId": "env-1"}}).encode()

        with TestClient(app) as client:
            assert client.post("/webhooks/docusign", content=body).status_code == 401
            mark.assert_not_awaited()
            res = client.post("/webhooks/docusign", content=body, headers={"X-DocuSign-Signature-1": self._sign(body)})
        assert res.status_code == 200 and res.json()["data"]["status"] == "signed"
        kwargs = mark.await_args.kwargs
        assert kwargs["provider_event_id"] == "docusign-env-1-completed"
        assert kwargs["signed_by"] == "signer@example.com"


def _contract(status="draft"):
    return MagicMock(id="c-1", status=status, vendor_id="v-1", purchase_request_id="pr-1")


def _db(already_tried=False, vendor_email=None):
    """execute() answers, in order: audit lookup, vendor contact email."""
    db = AsyncMock()
    tried = MagicMock(first=MagicMock(return_value=("a",) if already_tried else None))
    email = MagicMock(scalar_one_or_none=MagicMock(return_value=vendor_email))
    db.execute.side_effect = [tried, email]
    return db


class TestAutoSend:
    @pytest.fixture(autouse=True)
    def drop_folder_contract(self, monkeypatch):
        monkeypatch.setattr(contract_service, "is_drop_folder_contract", AsyncMock(return_value=True))
        monkeypatch.setattr(contract_service.settings, "esign_auto_send", True)
        monkeypatch.setattr(contract_service.settings, "esign_auto_signer_email", "signer@example.com")
        self.send = AsyncMock()
        monkeypatch.setattr(contract_service, "send_for_signature", self.send)
        self.audit = AsyncMock()
        monkeypatch.setattr(contract_service, "write_audit_log", self.audit)

    def test_drop_folder_contract_is_sent_once_through_the_auto_provider(self):
        assert run(contract_service.auto_send_for_signature(_db(), "producer", _contract())) == "sent"
        args, kwargs = self.send.await_args
        assert args[2:4] == ("c-1", "signer@example.com")
        assert kwargs["provider"] == "builtin" and kwargs["automatic"] is True  # built-in e-sign by default

    def test_never_sent_twice(self):
        assert run(contract_service.auto_send_for_signature(_db(already_tried=True), "p", _contract())) == "already_tried"
        assert run(contract_service.auto_send_for_signature(_db(), "p", _contract("pending_signature"))) == "skipped"
        self.send.assert_not_awaited()

    def test_in_app_requests_are_sent_too_by_default(self, monkeypatch):
        # FR-01: rule contract.auto_send_scope defaults to "all".
        monkeypatch.setattr(contract_service, "is_drop_folder_contract", AsyncMock(return_value=False))
        monkeypatch.setattr(contract_service, "auto_send_scope", lambda: "all")
        assert run(contract_service.auto_send_for_signature(_db(), "p", _contract())) == "sent"
        assert self.send.await_args.kwargs["automatic"] is True

    def test_scope_drop_folder_leaves_in_app_contracts_alone(self, monkeypatch):
        monkeypatch.setattr(contract_service, "is_drop_folder_contract", AsyncMock(return_value=False))
        monkeypatch.setattr(contract_service, "auto_send_scope", lambda: "drop_folder")
        assert run(contract_service.auto_send_for_signature(_db(), "p", _contract())) == "not_from_drop_folder"
        self.send.assert_not_awaited()

    def test_scope_drop_folder_still_sends_drop_folder_contracts(self, monkeypatch):
        monkeypatch.setattr(contract_service, "auto_send_scope", lambda: "drop_folder")
        assert run(contract_service.auto_send_for_signature(_db(), "p", _contract())) == "sent"

    def test_builtin_with_no_signer_goes_to_an_authorised_signatory(self, monkeypatch):
        # send_for_signature resolves signer None to an authorised signatory;
        # the vendor's contact email isn't one, so it isn't looked up.
        monkeypatch.setattr(contract_service.settings, "esign_auto_signer_email", None)
        monkeypatch.setattr(contract_service.settings, "esign_auto_provider", "builtin")
        assert run(contract_service.auto_send_for_signature(
            _db(vendor_email="sales@vendor.example"), "p", _contract())) == "sent"
        assert self.send.await_args.args[3] is None

    def test_scope_rule_value_is_checked(self, monkeypatch):
        monkeypatch.setattr("shared.rules_engine.get_rule", lambda key, fallback=None: "everything")
        assert contract_service.auto_send_scope() == "all"
        monkeypatch.setattr("shared.rules_engine.get_rule", lambda key, fallback=None: "drop_folder")
        assert contract_service.auto_send_scope() == "drop_folder"

    def test_falls_back_to_vendor_email_and_records_when_there_is_none(self, monkeypatch):
        # External providers email the signer, so they need an address.
        monkeypatch.setattr(contract_service.settings, "esign_auto_provider", "docusign")
        monkeypatch.setattr(contract_service.settings, "esign_auto_signer_email", None)
        assert run(contract_service.auto_send_for_signature(
            _db(vendor_email="sales@vendor.example"), "p", _contract())) == "sent"
        assert self.send.await_args.args[3] == "sales@vendor.example"

        self.send.reset_mock()
        assert run(contract_service.auto_send_for_signature(_db(), "p", _contract())) == "no_signer"
        self.send.assert_not_awaited()
        assert self.audit.await_args.args[3] == "auto_send_skipped"

    def test_provider_failure_is_recorded_not_retried_forever(self):
        self.send.side_effect = contract_service.ContractGenerationError("DocuSign login failed (400)")
        assert run(contract_service.auto_send_for_signature(_db(), "p", _contract())) == "failed"
        assert self.audit.await_args.args[3] == "auto_send_failed"
        assert "DocuSign login failed" in self.audit.await_args.args[4]["reason"]
