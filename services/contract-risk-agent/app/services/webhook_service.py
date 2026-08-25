import hashlib
import hmac
import json
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Contract, ProcessedWebhookEvent
from app.services.audit import write_audit_log


class WebhookSignatureError(Exception):
    pass


class WebhookReplayError(Exception):
    """Raised for an already-processed event id — callers treat this as a
    no-op success, not a failure, since webhook providers retry on
    anything but a 2xx."""
    pass


class WebhookContractNotFoundError(Exception):
    pass


def verify_signature(payload: dict, signature: str) -> None:
    """HMAC-SHA256 over the canonical JSON payload, shared-secret keyed.
    Constant-time comparison to avoid timing side channels."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    expected = hmac.new(settings.esign_webhook_secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise WebhookSignatureError("webhook signature verification failed")


async def handle_esign_webhook(db: AsyncSession, kafka_producer, payload: dict) -> Contract:
    """payload keys: provider_event_id, contract_id, signed_by, signed_at, signature."""
    signature = payload.get("signature", "")
    body = {k: v for k, v in payload.items() if k != "signature"}
    verify_signature(body, signature)

    provider_event_id = payload["provider_event_id"]
    existing = await db.get(ProcessedWebhookEvent, provider_event_id)
    if existing is not None:
        raise WebhookReplayError(f"webhook event {provider_event_id} already processed")

    contract = await db.get(Contract, payload["contract_id"])
    if contract is None:
        raise WebhookContractNotFoundError(f"contract {payload['contract_id']} not found")

    signed_at = datetime.fromisoformat(payload["signed_at"])
    contract.status = "signed"
    contract.signed_at = signed_at
    contract.signed_by = payload["signed_by"]
    contract.updated_at = datetime.now(timezone.utc)

    db.add(
        ProcessedWebhookEvent(
            provider_event_id=provider_event_id,
            contract_id=contract.id,
            processed_at=datetime.now(timezone.utc),
        )
    )
    await write_audit_log(
        db, "contract", contract.id, "signed_via_webhook",
        {"provider_event_id": provider_event_id, "signed_by": payload["signed_by"]},
    )
    await db.commit()
    await db.refresh(contract)

    if kafka_producer is not None:
        await kafka_producer.publish_contract_signed(contract)

    return contract
