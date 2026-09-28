import os
import sys
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

from app.api import contracts, webhooks
from app.database import get_db
from shared.auth import get_current_user
from shared.auth.middleware import CurrentUser


@pytest.fixture
def client():
    test_app = FastAPI()
    test_app.state.kafka_producer = AsyncMock()
    test_app.include_router(contracts.router, prefix="/contracts")
    test_app.include_router(webhooks.router, prefix="/webhooks")
    test_app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=str(uuid.uuid4()), email="approver@company.com", role="approver"
    )
    test_app.dependency_overrides[get_db] = lambda: AsyncMock()
    with TestClient(test_app) as c:
        yield c


class TestDigitalEsignIntegration:
    """Tests for real legally-binding electronic signature flow and certificates."""

    def test_post_sign_contract_success(self, client):
        contract_id = str(uuid.uuid4())
        mock_contract = MagicMock()
        mock_contract.id = contract_id
        mock_contract.purchase_request_id = str(uuid.uuid4())
        mock_contract.vendor_id = str(uuid.uuid4())
        mock_contract.template = "saas_subscription"
        mock_contract.version = 1
        mock_contract.status = "signed"
        mock_contract.renewal_type = "auto"
        mock_contract.notice_period_days = 30
        mock_contract.contract_end_date = None
        mock_contract.generated_at = datetime.now(timezone.utc)
        mock_contract.signed_at = datetime.now(timezone.utc)
        mock_contract.signed_by = "Alice Approver <alice@company.com>"
        mock_contract.esign_provider_ref = "builtin-seal-abcd1234efgh5678"
        mock_contract.reconciliation_status = None
        mock_contract.contract_text = "Standard Terms and Conditions..."

        mock_cert = {
            "certificate_id": str(uuid.uuid4()),
            "contract_id": contract_id,
            "template_used": "saas_subscription",
            "signer_name": "Alice Approver",
            "signer_email": "alice@company.com",
            "signed_at": datetime.now(timezone.utc).isoformat(),
            "signature_seal": "abcd1234efgh567890",
            "legal_framework": "ESIGN Act (15 U.S.C. § 7001) / UETA",
            "consent_acknowledged": True,
            "ip_address": "127.0.0.1",
            "user_agent": "TestAgent",
            "signature_image": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
        }

        with patch("app.services.contract_service.sign_contract_digitally", new=AsyncMock(return_value=(mock_contract, mock_cert))) as sign:
            resp = client.post(
                f"/contracts/{contract_id}/sign",
                json={
                    "signer_name": "Alice Approver",
                    "signer_email": "alice@company.com",
                    "signature_data": mock_cert["signature_image"],
                    "legal_consent": True,
                },
            )
            assert resp.status_code == 200
            data = resp.json()["data"]
            assert data["id"] == contract_id
            assert data["status"] == "signed"
            assert data["signed_by"] == "Alice Approver <alice@company.com>"
            assert data["signature_certificate"]["signature_seal"] == "abcd1234efgh567890"
            # The signer is the signed-in account, not the email in the body.
            assert sign.await_args.kwargs["signer_email"] == "approver@company.com"

    def test_get_signature_certificate(self, client):
        contract_id = str(uuid.uuid4())
        mock_cert = {
            "certificate_id": str(uuid.uuid4()),
            "contract_id": contract_id,
            "signer_name": "Alice Approver",
            "signer_email": "alice@company.com",
            "signed_at": datetime.now(timezone.utc).isoformat(),
            "signature_seal": "abcd1234efgh567890",
            "legal_framework": "ESIGN Act (15 U.S.C. § 7001) / UETA",
            "consent_acknowledged": True,
        }

        with patch("app.services.contract_service.get_signature_certificate", new=AsyncMock(return_value=mock_cert)):
            resp = client.get(f"/contracts/{contract_id}/signature-certificate")
            assert resp.status_code == 200
            assert resp.json()["data"]["certificate_id"] == mock_cert["certificate_id"]
            assert resp.json()["data"]["signature_seal"] == "abcd1234efgh567890"

    def test_requester_cannot_sign(self, client):
        client.app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            id=str(uuid.uuid4()), email="requester@company.com", role="requester"
        )
        with patch("app.services.contract_service.sign_contract_digitally", new=AsyncMock()) as sign:
            resp = client.post(f"/contracts/{uuid.uuid4()}/sign",
                               json={"signer_name": "Req", "legal_consent": True})
        assert resp.status_code == 403
        sign.assert_not_awaited()

    def test_unsigned_documenso_payload_rejected_on_esign_webhook(self, client):
        # /webhooks/esign only takes HMAC-signed payloads. Documenso's own
        # callbacks go to /webhooks/documenso, which checks its secret; an
        # unauthenticated "DOCUMENT_COMPLETED" here must not sign anything.
        with patch("app.services.webhook_service.mark_contract_signed", new=AsyncMock()) as mark:
            resp = client.post("/webhooks/esign", json={"event": "DOCUMENT_COMPLETED", "data": {}})
        assert resp.status_code == 422
        mark.assert_not_awaited()


def _contract(status="pending_signature", ref="builtin-ref-1234"):
    c = MagicMock()
    c.id, c.status, c.esign_provider_ref = str(uuid.uuid4()), status, ref
    c.contract_text, c.template = "Terms", "saas_subscription"
    return c


class TestSignContractDigitally:
    @pytest.fixture
    def db(self):
        db = AsyncMock()
        return db

    async def _sign(self, db, contract, consent=True):
        from app.services import contract_service
        db.get.return_value = contract
        return await contract_service.sign_contract_digitally(
            db, MagicMock(), contract.id, signer_name="Alice", signer_email="alice@company.com",
            legal_consent=consent,
        )

    @pytest.mark.asyncio
    async def test_signs_and_publishes_through_the_outbox(self, db):
        contract = _contract()
        outbox = AsyncMock()
        with patch("app.services.contract_service.staged", return_value=outbox), \
                patch("app.services.contract_service.write_audit_log", new=AsyncMock()) as audit:
            signed, cert = await self._sign(db, contract)
        assert signed.status == "signed" and signed.signed_by == "Alice <alice@company.com>"
        assert cert["signer_email"] == "alice@company.com" and len(cert["signature_seal"]) == 64
        outbox.publish_contract_signed.assert_awaited_once()
        assert audit.await_args.args[3] == "digitally_signed"

    @pytest.mark.asyncio
    async def test_consent_required(self, db):
        from app.services.contract_service import ContractGenerationError
        with pytest.raises(ContractGenerationError):
            await self._sign(db, _contract(), consent=False)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", ["terminated", "expired"])
    async def test_only_unsigned_live_contracts(self, db, status):
        from app.services.contract_service import ContractGenerationError
        with pytest.raises(ContractGenerationError):
            await self._sign(db, _contract(status=status))

    @pytest.mark.asyncio
    async def test_live_documenso_contract_completes_in_documenso(self, db):
        from app.services.contract_service import ContractGenerationError
        with pytest.raises(ContractGenerationError):
            await self._sign(db, _contract(ref="documenso-doc-42"))

    @pytest.mark.asyncio
    async def test_no_certificate_invented_for_other_signatures(self, db):
        from app.services import contract_service
        res = MagicMock()
        res.scalars.return_value.first.return_value = None
        db.execute.return_value = res
        assert await contract_service.get_signature_certificate(db, str(uuid.uuid4())) is None
