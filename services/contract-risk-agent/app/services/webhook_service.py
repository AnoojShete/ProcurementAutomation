import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
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
    """Handles both Documenso webhook callbacks and standard HMAC webhook callbacks.
    Standard payload keys: provider_event_id, contract_id, signed_by, signed_at, signature.
    Documenso payload keys: event ('DOCUMENT_COMPLETED'), data: { id, recipients, ... }
    """
    # 1. Handle Documenso webhook format
    if "event" in payload and payload.get("event") in ("DOCUMENT_COMPLETED", "DOCUMENT_SIGNED", "document.completed", "document.signed"):
        doc_data = payload.get("data", {})
        doc_id = str(doc_data.get("id") or "")
        provider_event_id = str(payload.get("id") or f"documenso-{doc_id}-{payload.get('event')}")

        existing = await db.get(ProcessedWebhookEvent, provider_event_id)
        if existing is not None:
            raise WebhookReplayError(f"webhook event {provider_event_id} already processed")

        # Find contract by provider reference containing doc_id
        stmt = select(Contract).where(Contract.esign_provider_ref.like(f"%{doc_id}%"))
        res = await db.execute(stmt)
        contract = res.scalars().first()
        if contract is None:
            raise WebhookContractNotFoundError(f"contract for documenso document {doc_id} not found")

        recipients = doc_data.get("recipients", [])
        signed_by = "documenso-signer"
        if recipients and isinstance(recipients, list):
            for r in recipients:
                if r.get("email"):
                    signed_by = f"{r.get('name', 'Signer')} <{r.get('email')}>"
                    break

        signed_at = datetime.now(timezone.utc)
        contract.status = "signed"
        contract.signed_at = signed_at
        contract.signed_by = signed_by
        contract.updated_at = signed_at

        db.add(
            ProcessedWebhookEvent(
                provider_event_id=provider_event_id,
                contract_id=contract.id,
                processed_at=signed_at,
            )
        )
        await write_audit_log(
            db, "contract", contract.id, "signed_via_webhook",
            {"provider": "documenso", "provider_event_id": provider_event_id, "signed_by": signed_by},
        )
        await db.commit()
        await db.refresh(contract)

        if kafka_producer is not None:
            await kafka_producer.publish_contract_signed(contract)

        return contract

    # 2. Standard HMAC-authenticated webhook format
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
