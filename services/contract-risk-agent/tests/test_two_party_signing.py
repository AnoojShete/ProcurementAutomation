"""Two-party signing through Documenso (app/services/signing_service.py):
who may open the signing frame, the vendor's link, and what each webhook
does to the contract."""
import hashlib
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

import pytest

from app.models import Contract, ContractSigner, Vendor
from app.services import contract_service, esign_client, signing_service, webhook_service
from app.services.contract_pdf import A4, render_contract_pdf
from tests.test_contract_documents import _pdf_input

CID = "11111111-1111-1111-1111-111111111111"
ENVELOPE = "envelope_abc"
NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)


def _contract(**kw):
    base = dict(id=CID, vendor_id="v-1", status="pending_signature", esign_provider_ref=f"documenso-env-{ENVELOPE}",
                contract_text="SAAS SUBSCRIPTION AGREEMENT\n1. TERMS", purchase_request_id=None, updated_at=None,
                signed_at=None, signed_by=None)
    base.update(kw)
    return SimpleNamespace(**base)


def _signer(party, **kw):
    base = dict(contract_id=CID, party=party, name="CFO" if party == "company" else "Priya Raman",
                email="cfo@acme.test" if party == "company" else "priya@vendor.test",
                signing_order=1 if party == "company" else 2,
                provider_recipient_id="7" if party == "company" else "8",
                provider_token=f"tok-{party}", link_token_sha256=None, link_expires_at=None,
                status="ready" if party == "company" else "waiting", signed_at=None, rejection_reason=None)
    base.update(kw)
    return SimpleNamespace(**base)


class FakeDB:
    def __init__(self, contract, signers, vendor=None):
        self.contract, self.signers, self.added, self.commits = contract, signers, [], 0
        self.vendor = vendor or SimpleNamespace(name="Vendor Pvt Ltd", contact_email=None)

    async def get(self, model, _id):
        return {Contract: self.contract, Vendor: self.vendor}.get(model)

    def add(self, obj):
        self.added.append(obj)

    async def execute(self, *_a, **_kw):
        return None

    async def commit(self):
        self.commits += 1

    async def refresh(self, _obj):
        pass


@pytest.fixture
def env(monkeypatch):
    """Signers kept in FakeDB.signers; audit, mail and the final 'signed'
    step recorded instead of done."""
    state = SimpleNamespace(audit=[], mails=[], marked=[], db=None)

    async def signers_of(db, contract_id):
        return sorted(db.signers, key=lambda s: s.signing_order)

    async def one(db, contract_id, party):
        return next((s for s in db.signers if s.party == party), None)

    async def by_link(db, token):
        h = hashlib.sha256(token.encode()).hexdigest()
        found = next((s for s in db.signers if s.link_token_sha256 == h), None)
        if found is None:
            raise signing_service.SigningLinkInvalid("bad link")
        return found

    async def audit(db, entity, entity_id, action, payload):
        state.audit.append((action, payload))

    async def send_email(to, subject, text, html=None):
        state.mails.append((to, subject, text))

    async def mark(db, kp, **kw):
        state.marked.append(kw)
        db.contract.status = "signed"
        return db.contract

    async def risk(db, vendor_id, spend_amount=None, contract_id=None):
        return state.risk

    state.risk = {"signing_blocked": False, "acknowledgement_required": False, "risk_band": "Low", "risk_score": 10}
    monkeypatch.setattr(signing_service, "signers_of", signers_of)
    monkeypatch.setattr(signing_service, "_signer", one)
    monkeypatch.setattr(signing_service, "_by_link", by_link)
    monkeypatch.setattr(signing_service, "write_audit_log", audit)
    monkeypatch.setattr(signing_service, "signing_risk", risk)
    monkeypatch.setattr(signing_service, "_contract_amount", AsyncMock(return_value=4800.0))
    monkeypatch.setattr(webhook_service, "mark_contract_signed", mark)
    import shared.mailer
    monkeypatch.setattr(shared.mailer, "send_email", send_email)
    monkeypatch.setattr(shared.mailer, "load_settings", lambda: SimpleNamespace(app_base_url="http://portal.test"))
    monkeypatch.setattr(signing_service.settings, "documenso_public_url", "http://esign.test")
    return state


def _event(event, company="SIGNED", vendor="NOT_SIGNED", envelope=ENVELOPE, vendor_reason=None):
    return {"event": event, "payload": {
        "id": 3, "externalId": CID, "envelopeId": envelope, "status": "PENDING",
        "recipients": [
            {"id": 7, "email": "cfo@acme.test", "signingStatus": company, "signedAt": "2026-10-30T10:00:00.000Z"},
            {"id": 8, "email": "priya@vendor.test", "signingStatus": vendor, "signedAt":
                "2026-10-30T11:00:00.000Z" if vendor == "SIGNED" else None, "rejectionReason": vendor_reason},
        ]}}


class TestWebhook:
    @pytest.mark.asyncio
    async def test_company_signature_emails_the_vendor_a_link(self, env):
        db = FakeDB(_contract(), [_signer("company"), _signer("vendor")])
        assert await signing_service.handle_documenso_event(db, None, _event("DOCUMENT_RECIPIENT_COMPLETED")) is None
        company, vendor = db.signers
        assert company.status == "signed" and company.signed_at == datetime(2026, 10, 30, 10, tzinfo=timezone.utc)
        assert vendor.status == "ready" and vendor.link_expires_at > datetime.now(timezone.utc) + timedelta(days=29)
        (to, subject, text), = env.mails
        assert to == "priya@vendor.test"
        token = text.split("/sign#token=")[1].split()[0]
        # Only the token's hash is stored; the token itself is only in the email.
        assert vendor.link_token_sha256 == hashlib.sha256(token.encode()).hexdigest()
        assert [a for a, _ in env.audit] == ["company_signed", "vendor_link_sent"]
        assert db.contract.status == "pending_signature" and not env.marked

    @pytest.mark.asyncio
    async def test_a_replayed_webhook_changes_nothing(self, env):
        db = FakeDB(_contract(), [_signer("company"), _signer("vendor")])
        await signing_service.handle_documenso_event(db, None, _event("DOCUMENT_RECIPIENT_COMPLETED"))
        link_hash = db.signers[1].link_token_sha256
        await signing_service.handle_documenso_event(db, None, _event("DOCUMENT_RECIPIENT_COMPLETED"))
        assert len(env.mails) == 1 and db.signers[1].link_token_sha256 == link_hash

    @pytest.mark.asyncio
    async def test_an_event_about_an_earlier_envelope_is_ignored(self, env):
        db = FakeDB(_contract(), [_signer("company"), _signer("vendor")])
        await signing_service.handle_documenso_event(db, None, _event("DOCUMENT_COMPLETED", vendor="SIGNED",
                                                                      envelope="envelope_old"))
        assert db.signers[0].status == "ready" and not env.marked and not env.mails

    @pytest.mark.asyncio
    async def test_both_signatures_make_the_contract_signed(self, env):
        db = FakeDB(_contract(), [_signer("company", status="signed", signed_at=NOW), _signer("vendor", status="ready")])
        await signing_service.handle_documenso_event(db, None, _event("DOCUMENT_COMPLETED", vendor="SIGNED"))
        (kw,) = env.marked
        assert kw["contract_id"] == CID and kw["provider_event_id"] == f"documenso-{ENVELOPE}-completed"
        assert "cfo@acme.test" in kw["signed_by"] and "priya@vendor.test" in kw["signed_by"]
        assert kw["signed_at"] == datetime(2026, 10, 30, 11, tzinfo=timezone.utc)
        assert [a for a, _ in env.audit] == ["vendor_signed"]

    @pytest.mark.asyncio
    async def test_one_signature_never_makes_the_contract_signed(self, env):
        db = FakeDB(_contract(), [_signer("company"), _signer("vendor")])
        # Even a DOCUMENT_COMPLETED that says only one of them signed.
        await signing_service.handle_documenso_event(db, None, _event("DOCUMENT_COMPLETED"))
        assert not env.marked and db.contract.status == "pending_signature"

    @pytest.mark.asyncio
    async def test_a_decline_sends_the_contract_back_to_draft(self, env):
        db = FakeDB(_contract(), [_signer("company", status="signed", signed_at=NOW), _signer("vendor", status="ready")])
        await signing_service.handle_documenso_event(
            db, None, _event("DOCUMENT_REJECTED", vendor="REJECTED", vendor_reason="Wrong liability cap"))
        assert db.contract.status == "draft" and db.contract.esign_provider_ref is None
        assert db.signers[1].status == "rejected" and db.signers[1].rejection_reason == "Wrong liability cap"
        assert ("signature_declined", {"party": "vendor", "signer_email": "priya@vendor.test",
                                       "reason": "Wrong liability cap"}) in env.audit
        assert not env.marked


class TestCompanySession:
    @pytest.mark.asyncio
    async def test_only_the_named_signatory_gets_the_frame(self, env):
        db = FakeDB(_contract(), [_signer("company"), _signer("vendor")])
        with pytest.raises(signing_service.NotTheSigner):
            await signing_service.company_session(db, CID, "approver@acme.test")
        session = await signing_service.company_session(db, CID, "CFO@acme.test")
        assert session["token"] == "tok-company" and session["host"] == "http://esign.test"
        assert env.audit[-1][0] == "signing_opened"

    @pytest.mark.asyncio
    async def test_risk_must_be_acknowledged_when_required(self, env):
        env.risk = {**env.risk, "acknowledgement_required": True, "acknowledgement_reason": "High risk."}
        db = FakeDB(_contract(), [_signer("company"), _signer("vendor")])
        with pytest.raises(contract_service.RiskAcknowledgementRequired):
            await signing_service.company_session(db, CID, "cfo@acme.test")
        session = await signing_service.company_session(db, CID, "cfo@acme.test", risk_acknowledged=True)
        assert session["token"] == "tok-company"
        assert env.audit[-1][1]["vendor_risk_at_signing"]["acknowledged"] is True

    @pytest.mark.asyncio
    async def test_a_blocked_vendor_cant_be_signed_even_acknowledged(self, env):
        env.risk = {**env.risk, "signing_blocked": True, "blocked_reason": "Sanctions match."}
        db = FakeDB(_contract(), [_signer("company"), _signer("vendor")])
        with pytest.raises(contract_service.VendorBlocked):
            await signing_service.company_session(db, CID, "cfo@acme.test", risk_acknowledged=True)

    @pytest.mark.asyncio
    async def test_no_second_signature(self, env):
        db = FakeDB(_contract(), [_signer("company", status="signed"), _signer("vendor", status="ready")])
        with pytest.raises(contract_service.ContractGenerationError):
            await signing_service.company_session(db, CID, "cfo@acme.test")


class TestVendorSession:
    def _db(self, **vendor):
        token = "link-" + uuid.uuid4().hex
        signer = _signer("vendor", **{"status": "ready", "link_token_sha256": hashlib.sha256(token.encode()).hexdigest(),
                                      "link_expires_at": datetime.now(timezone.utc) + timedelta(days=5), **vendor})
        return FakeDB(_contract(), [_signer("company", status="signed", signed_at=NOW), signer]), token

    @pytest.mark.asyncio
    async def test_link_opens_the_vendors_frame(self, env):
        db, token = self._db()
        session = await signing_service.vendor_session(db, token)
        assert session["state"] == "ready" and session["token"] == "tok-vendor"
        assert session["signer_email"] == "priya@vendor.test" and session["company_signed_at"]

    @pytest.mark.asyncio
    async def test_unknown_link(self, env):
        db, _ = self._db()
        with pytest.raises(signing_service.SigningLinkInvalid):
            await signing_service.vendor_session(db, "made-up-token-0000000000")

    @pytest.mark.asyncio
    async def test_expired_link_gives_no_token(self, env):
        db, token = self._db(link_expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
        session = await signing_service.vendor_session(db, token)
        assert session["state"] == "expired" and "token" not in session

    @pytest.mark.asyncio
    async def test_after_signing_the_link_gives_no_token(self, env):
        db, token = self._db(status="signed", signed_at=NOW)
        session = await signing_service.vendor_session(db, token)
        assert session["state"] == "signed" and "token" not in session

    @pytest.mark.asyncio
    async def test_a_new_link_replaces_the_old_one(self, env):
        db, token = self._db()
        await signing_service.resend_vendor_link(db, CID)
        with pytest.raises(signing_service.SigningLinkInvalid):
            await signing_service.vendor_session(db, token)
        new_token = env.mails[-1][2].split("/sign#token=")[1].split()[0]
        assert (await signing_service.vendor_session(db, new_token))["state"] == "ready"


class TestSend:
    @pytest.mark.asyncio
    async def test_needs_someone_to_sign_for_the_vendor(self, env):
        db = FakeDB(_contract(status="draft", esign_provider_ref=None), [])
        with pytest.raises(contract_service.ContractGenerationError, match="vendor"):
            await signing_service.send_two_party(db, None, db.contract, "cfo@acme.test", None)
        with pytest.raises(contract_service.ContractGenerationError, match="someone other"):
            await signing_service.send_two_party(db, None, db.contract, "cfo@acme.test", "CFO@acme.test")

    @pytest.mark.asyncio
    async def test_a_blocked_vendors_contract_never_goes_out(self, env, monkeypatch):
        env.risk = {**env.risk, "signing_blocked": True, "blocked_reason": "Sanctions match."}
        send = AsyncMock()
        monkeypatch.setattr(esign_client, "documenso_send_envelope", send)
        db = FakeDB(_contract(status="draft", esign_provider_ref=None), [])
        with pytest.raises(contract_service.VendorBlocked):
            await signing_service.send_two_party(db, None, db.contract, "cfo@acme.test", "priya@vendor.test")
        send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_sends_both_signers_with_fields_on_their_lines(self, env, monkeypatch):
        captured = {}

        async def send(contract_id, title, pdf, signers):
            captured.update(pdf=pdf, signers=signers)
            return f"documenso-env-{ENVELOPE}", [
                esign_client.EnvelopeRecipient("company", "cfo@acme.test", "7", "tok-c"),
                esign_client.EnvelopeRecipient("vendor", "priya@vendor.test", "8", "tok-v"),
            ]

        monkeypatch.setattr(esign_client, "documenso_send_envelope", send)
        monkeypatch.setattr(signing_service, "build_pdf_input", AsyncMock(return_value=_pdf_input()))
        monkeypatch.setattr(signing_service, "_display_name", AsyncMock(return_value="Chief Financial Officer"))
        db = FakeDB(_contract(status="draft", esign_provider_ref=None), [])
        await signing_service.send_two_party(db, None, db.contract, "cfo@acme.test", "Priya@Vendor.test", "Priya Raman")
        company, vendor = captured["signers"]
        assert (company.party, company.email, company.name) == ("company", "cfo@acme.test", "Chief Financial Officer")
        assert (vendor.party, vendor.email, vendor.name) == ("vendor", "priya@vendor.test", "Priya Raman")
        assert company.field["page"] == vendor.field["page"]
        assert company.field["positionX"] < 50 < vendor.field["positionX"]
        # The signed copy is the final one: no DRAFT watermark.
        assert b"DRAFT" not in captured["pdf"]
        assert db.contract.status == "pending_signature" and db.contract.esign_provider_ref == f"documenso-env-{ENVELOPE}"
        assert [(s.party, s.status, s.provider_token) for s in db.added] == [
            ("company", "ready", "tok-c"), ("vendor", "waiting", "tok-v")]


def test_signature_lines_are_recorded_where_they_are_drawn():
    slots = {}
    render_contract_pdf(_pdf_input(), slots=slots)
    company, vendor = slots["company"], slots["vendor"]
    assert company.page == vendor.page and company.y == vendor.y
    assert company.x < vendor.x and company.width > 100
    pct = company.as_percentages()
    assert 0 < pct["positionX"] < 50 and 0 < pct["positionY"] < 100
    # Percent from the top: the box's top edge.
    assert pct["positionY"] == round((A4[1] - company.y - company.height) / A4[1] * 100, 2)


# A 1x1 PNG, as Documenso stores a drawn signature.
SIGNATURE_PNG = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
                 "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


def _pdf_text(pdf: bytes) -> bytes:
    """Every page stream of a ReportLab PDF, decompressed."""
    import base64
    import re
    import zlib
    out = []
    for raw in re.findall(rb"stream\r?\n(.*?)endstream", pdf, re.S):
        try:
            out.append(zlib.decompress(base64.a85decode(raw.strip(), adobe=True)))
        except Exception:
            continue  # an image's stream
    return b"\n".join(out)


class TestCompanySignedCopy:
    """While the vendor hasn't signed: the agreement with our signature,
    marked as not yet executed."""

    @pytest.fixture
    def copy_env(self, env, monkeypatch):
        monkeypatch.setattr(signing_service, "build_pdf_input",
                            AsyncMock(side_effect=lambda db, c: _pdf_input(contract_id=CID, status="pending_signature")))
        env.recipient = []

        async def image(recipient_id):
            env.recipient.append(recipient_id)
            return env.image
        env.image = SIGNATURE_PNG
        monkeypatch.setattr(esign_client, "documenso_signature_image", image)
        return env

    @pytest.mark.asyncio
    async def test_has_our_drawn_signature_and_the_awaiting_vendor_line(self, copy_env):
        db = FakeDB(_contract(), [_signer("company", status="signed", signed_at=NOW), _signer("vendor", status="ready")])
        pdf = await signing_service.company_signed_copy(db, db.contract)
        text = _pdf_text(pdf)
        assert copy_env.recipient == ["7"]
        assert b"/Subtype /Image" in pdf
        assert b"awaiting the vendor" in text and b"Not an executed agreement" in text
        assert b"CFO" in text and b"30 Oct 2026, 12:00 UTC" in text
        assert b"DRAFT" not in text

    @pytest.mark.asyncio
    async def test_falls_back_to_the_name_when_the_drawn_signature_cant_be_read(self, copy_env):
        copy_env.image = None
        db = FakeDB(_contract(), [_signer("company", status="signed", signed_at=NOW), _signer("vendor", status="ready")])
        pdf = await signing_service.company_signed_copy(db, db.contract)
        assert b"/Subtype /Image" not in pdf
        assert b"CFO" in _pdf_text(pdf) and b"awaiting the vendor" in _pdf_text(pdf)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("company_status,contract_status", [
        ("ready", "pending_signature"),  # we haven't signed yet
        ("signed", "signed"),            # both signed: Documenso's sealed copy instead
        ("signed", "draft"),             # declined and back to draft
    ])
    async def test_none_unless_only_we_have_signed(self, copy_env, company_status, contract_status):
        db = FakeDB(_contract(status=contract_status), [_signer("company", status=company_status), _signer("vendor")])
        assert await signing_service.company_signed_copy(db, db.contract) is None

    @pytest.mark.asyncio
    async def test_signature_read_failure_is_not_an_error(self, monkeypatch):
        monkeypatch.setattr(esign_client.settings, "documenso_api_url", "http://documenso.test")
        monkeypatch.setattr(esign_client.settings, "documenso_api_token", "t")
        import asyncpg
        monkeypatch.setattr(asyncpg, "connect", AsyncMock(side_effect=OSError("connection refused")))
        assert await esign_client.documenso_signature_image("7") is None

    def test_documenso_database_is_next_to_ours(self, monkeypatch):
        monkeypatch.setattr(esign_client.settings, "documenso_database_url", None)
        monkeypatch.setattr(esign_client.settings, "database_url", "postgresql+asyncpg://u:p@postgres:5432/postgres")
        assert esign_client._documenso_dsn() == "postgresql://u:p@postgres:5432/documenso"


def test_download_while_waiting_for_the_vendor_is_the_company_signed_copy(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api import contracts
    from app.database import get_db
    from shared.auth import get_current_user
    from shared.auth.middleware import CurrentUser

    app = FastAPI()
    app.include_router(contracts.router, prefix="/contracts")
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id="u", email="a@b.com", role="finance")
    app.dependency_overrides[get_db] = lambda: AsyncMock()
    contract = SimpleNamespace(id="c1234567-aaaa", status="pending_signature", version=1)
    monkeypatch.setattr(contract_service, "get_contract", AsyncMock(return_value=contract))
    monkeypatch.setattr(signing_service, "company_signed_copy", AsyncMock(return_value=b"%PDF-1.4 ours"))
    with TestClient(app) as client:
        resp = client.get("/contracts/c1234567-aaaa/signed-document")
    assert resp.status_code == 200
    assert 'filename="contract-c1234567-v1-signed-by-company.pdf"' in resp.headers["content-disposition"]
    assert resp.content == b"%PDF-1.4 ours"
