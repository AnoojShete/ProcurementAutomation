import hashlib
import hmac
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.database import get_db
from app.models import Contract, ProcessedWebhookEvent
from app.services import webhook_service
from app.services.webhook_service import (
    verify_signature,
    handle_esign_webhook,
    WebhookSignatureError,
    WebhookReplayError,
    WebhookContractNotFoundError,
)
from shared.auth import get_current_user
from shared.auth.middleware import CurrentUser


def _make_signed_payload(contract_id: str, event_id: str, secret: str = settings.esign_webhook_secret, **kwargs):
    payload = {
        "provider_event_id": event_id,
        "contract_id": contract_id,
        "signed_by": kwargs.get("signed_by", "signer@example.com"),
        "signed_at": kwargs.get("signed_at", "2026-09-25T12:00:00+00:00"),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
    payload["signature"] = sig
    return payload


class TestEsignWebhookLogic:
    """Direct unit tests for HMAC signature verification and webhook processing logic."""

    def test_verify_signature_valid(self):
        body = {"contract_id": "c-1", "provider_event_id": "e-1"}
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        sig = hmac.new(settings.esign_webhook_secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
        # Should not raise
        verify_signature(body, sig)

    def test_verify_signature_invalid(self):
        body = {"contract_id": "c-1", "provider_event_id": "e-1"}
        with pytest.raises(WebhookSignatureError):
            verify_signature(body, "bad-signature-hash")

    def test_verify_signature_tampered_payload(self):
        body = {"contract_id": "c-1", "provider_event_id": "e-1"}
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        sig = hmac.new(settings.esign_webhook_secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()

        tampered = {"contract_id": "c-1", "provider_event_id": "e-1", "extra": "tampered"}
        with pytest.raises(WebhookSignatureError):
            verify_signature(tampered, sig)

    @pytest.mark.asyncio
    async def test_handle_esign_webhook_success(self):
        contract_id = str(uuid.uuid4())
        event_id = f"evt_{uuid.uuid4()}"
        payload = _make_signed_payload(contract_id, event_id)

        mock_contract = Contract(
            id=contract_id,
            status="pending_signature",
            template="hardware_purchase",
            version=1,
        )

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        # First call checks ProcessedWebhookEvent -> None; second checks Contract -> mock_contract
        mock_db.get.side_effect = lambda model, pk: None if model == ProcessedWebhookEvent else mock_contract

        mock_kafka = AsyncMock()

        contract = await handle_esign_webhook(mock_db, mock_kafka, payload)

        assert contract.status == "signed"
        assert contract.signed_by == "signer@example.com"
        assert mock_db.add.called
        assert mock_db.commit.called
        assert mock_kafka.publish_contract_signed.called

    @pytest.mark.asyncio
    async def test_handle_esign_webhook_replay_rejected(self):
        contract_id = str(uuid.uuid4())
        event_id = f"evt_duplicate_{uuid.uuid4()}"
        payload = _make_signed_payload(contract_id, event_id)

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        # Returns an already existing ProcessedWebhookEvent
        mock_db.get.return_value = ProcessedWebhookEvent(
            provider_event_id=event_id,
            contract_id=contract_id,
            processed_at=datetime.now(timezone.utc),
        )

        with pytest.raises(WebhookReplayError) as exc_info:
            await handle_esign_webhook(mock_db, AsyncMock(), payload)

        assert "already processed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_handle_esign_webhook_contract_not_found(self):
        contract_id = str(uuid.uuid4())
        event_id = f"evt_{uuid.uuid4()}"
        payload = _make_signed_payload(contract_id, event_id)

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        # No existing webhook event, but contract is None
        mock_db.get.side_effect = lambda model, pk: None

        with pytest.raises(WebhookContractNotFoundError):
            await handle_esign_webhook(mock_db, AsyncMock(), payload)


class TestEsignWebhookEndpoints:
    """HTTP endpoint tests for POST /webhooks/esign and POST /contracts/{id}/sign-simulated."""

    @pytest.fixture
    def client(self):
        from fastapi import FastAPI
        from app.api import webhooks, contracts

        test_app = FastAPI()
        test_app.state.kafka_producer = AsyncMock()
        test_app.include_router(webhooks.router, prefix="/webhooks")
        test_app.include_router(contracts.router, prefix="/contracts")
        test_app.dependency_overrides[get_current_user] = lambda: CurrentUser(id="user-1", email="a@b.com", role="admin")
        test_app.dependency_overrides[get_db] = lambda: AsyncMock()

        with TestClient(test_app) as c:
            yield c

    def test_post_webhook_esign_valid_signature(self, client):
        contract_id = str(uuid.uuid4())
        event_id = f"evt_{uuid.uuid4()}"
        payload = _make_signed_payload(contract_id, event_id)

        mock_contract = MagicMock()
        mock_contract.id = contract_id
        mock_contract.status = "signed"

        with patch("app.services.webhook_service.handle_esign_webhook", new=AsyncMock(return_value=mock_contract)):
            resp = client.post("/webhooks/esign", json=payload)
            assert resp.status_code == 200
            data = resp.json()["data"]
            assert data["contract_id"] == contract_id
            assert data["status"] == "signed"

    def test_post_webhook_esign_invalid_signature_rejected(self, client):
        contract_id = str(uuid.uuid4())
        event_id = f"evt_{uuid.uuid4()}"
        payload = _make_signed_payload(contract_id, event_id, secret="wrong-secret")

        with patch("app.services.webhook_service.handle_esign_webhook", side_effect=WebhookSignatureError("invalid webhook signature")):
            resp = client.post("/webhooks/esign", json=payload)
            assert resp.status_code == 401
            assert resp.json()["detail"] == "invalid webhook signature"

    def test_post_webhook_esign_replay_handled(self, client):
        contract_id = str(uuid.uuid4())
        event_id = f"evt_replay_{uuid.uuid4()}"
        payload = _make_signed_payload(contract_id, event_id)

        with patch("app.services.webhook_service.handle_esign_webhook", side_effect=WebhookReplayError("already processed")):
            resp = client.post("/webhooks/esign", json=payload)
            assert resp.status_code == 200
            assert resp.json()["data"]["status"] == "already_processed"

    def test_post_webhook_esign_contract_not_found(self, client):
        contract_id = str(uuid.uuid4())
        event_id = f"evt_{uuid.uuid4()}"
        payload = _make_signed_payload(contract_id, event_id)

        with patch("app.services.webhook_service.handle_esign_webhook", side_effect=WebhookContractNotFoundError(f"contract {contract_id} not found")):
            resp = client.post("/webhooks/esign", json=payload)
            assert resp.status_code == 404
            assert f"contract {contract_id} not found" in resp.json()["detail"]

    def test_sign_simulated_forbidden_when_real_provider_configured(self, client):
        """Simulated endpoint must return 403 Forbidden when real provider is configured or simulated signatures disabled."""
        contract_id = str(uuid.uuid4())

        with patch.object(settings, "allow_simulated_signatures", False):
            resp = client.post(f"/contracts/{contract_id}/sign-simulated")
            assert resp.status_code == 403
            assert "Simulated signatures are disabled" in resp.json()["detail"]

        with patch.object(settings, "documenso_api_url", "https://documenso.internal:3000"):
            resp = client.post(f"/contracts/{contract_id}/sign-simulated")
            assert resp.status_code == 403
            assert "Simulated signatures are disabled" in resp.json()["detail"]

