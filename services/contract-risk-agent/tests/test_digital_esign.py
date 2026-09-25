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

        with patch("app.services.contract_service.sign_contract_digitally", new=AsyncMock(return_value=(mock_contract, mock_cert))):
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

    def test_documenso_webhook_event_accepted(self, client):
        contract_id = str(uuid.uuid4())
        documenso_payload = {
            "event": "DOCUMENT_COMPLETED",
            "data": {
                "id": 88219,
                "title": "Procurement Contract",
                "status": "COMPLETED",
                "recipients": [
                    {
                        "name": "Jane Vendor",
                        "email": "jane@vendor.com",
                        "signingStatus": "SIGNED",
                    }
                ],
            },
        }

        mock_contract = MagicMock()
        mock_contract.id = contract_id
        mock_contract.status = "signed"

        with patch("app.services.webhook_service.handle_esign_webhook", new=AsyncMock(return_value=mock_contract)):
            resp = client.post("/webhooks/esign", json=documenso_payload)
            assert resp.status_code == 200
            assert resp.json()["data"]["status"] == "signed"
