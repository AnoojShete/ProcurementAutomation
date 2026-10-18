import hashlib
import hmac
import json
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Contract, ProcessedWebhookEvent
from app.services.audit import write_audit_log
from shared.eventing import staged


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
    """payload keys: provider_event_id, contract_id, signed_by, signed_at, signature.
    Always HMAC-verified. Documenso's callbacks go to POST /webhooks/documenso,
    which checks Documenso's own secret (handle_documenso_webhook)."""
    signature = payload.get("signature", "")
    body = {k: v for k, v in payload.items() if k != "signature"}
    verify_signature(body, signature)

    return await mark_contract_signed(
        db, kafka_producer,
        contract_id=payload["contract_id"],
        signed_by=payload["signed_by"],
        signed_at=datetime.fromisoformat(payload["signed_at"]),
        provider_event_id=payload["provider_event_id"],
    )


async def mark_contract_signed(
    db: AsyncSession, kafka_producer, contract_id: str, signed_by: str, signed_at: datetime,
    provider_event_id: str, source: str = "signed_via_webhook",
) -> Contract:
    """Shared by every provider webhook: idempotent on provider_event_id."""
    existing = await db.get(ProcessedWebhookEvent, provider_event_id)
    if existing is not None:
        raise WebhookReplayError(f"webhook event {provider_event_id} already processed")

    contract = await db.get(Contract, contract_id)
    if contract is None:
        raise WebhookContractNotFoundError(f"contract {contract_id} not found")

    contract.status = "signed"
    contract.signed_at = signed_at
    contract.signed_by = signed_by
    contract.updated_at = datetime.now(timezone.utc)

    db.add(
        ProcessedWebhookEvent(
            provider_event_id=provider_event_id,
            contract_id=contract.id,
            processed_at=datetime.now(timezone.utc),
        )
    )
    await write_audit_log(
        db, "contract", contract.id, source,
        {"provider_event_id": provider_event_id, "signed_by": signed_by},
    )
    # contract.signed is committed with the contract (outbox), so the
    # request downstream can't be left at 'approved' by a lost publish.
    outbox = staged(kafka_producer, db)
    if outbox is not None:
        await outbox.publish_contract_signed(contract)
    try:
        await db.commit()
    except IntegrityError:
        # A concurrent delivery of the same provider_event_id committed
        # first — the check-then-insert above isn't atomic, so this is
        # caught here via the ProcessedWebhookEvent primary key instead.
        await db.rollback()
        raise WebhookReplayError(f"webhook event {provider_event_id} already processed")
    await db.refresh(contract)
    return contract


def verify_documenso_secret(received: str | None) -> None:
    """Documenso authenticates webhooks by echoing the endpoint's
    configured secret in X-Documenso-Secret (no body signature)."""
    expected = settings.documenso_webhook_secret
    if not expected or not received or not hmac.compare_digest(expected, received):
        raise WebhookSignatureError("invalid Documenso webhook secret")


async def handle_documenso_webhook(db: AsyncSession, kafka_producer, body: dict, secret: str | None) -> Contract | None:
    """Returns the updated contract for DOCUMENT_COMPLETED, None for any
    other event (acknowledged and ignored)."""
    verify_documenso_secret(secret)
    if body.get("event") != "DOCUMENT_COMPLETED":
        return None
    doc = body.get("payload") or {}
    contract_id = doc.get("externalId")
    if not contract_id:
        raise WebhookContractNotFoundError("Documenso document has no externalId (not created by this platform)")

    signers = [r for r in doc.get("recipients") or [] if r.get("role", "SIGNER") == "SIGNER"]
    signed_by = ", ".join(r.get("email", "") for r in signers if r.get("email")) or "unknown signer"
    completed = doc.get("completedAt") or (signers[0].get("signedAt") if signers else None)
    signed_at = datetime.fromisoformat(completed.replace("Z", "+00:00")) if completed else datetime.now(timezone.utc)

    return await mark_contract_signed(
        db, kafka_producer, contract_id=contract_id, signed_by=signed_by, signed_at=signed_at,
        provider_event_id=f"documenso-{doc.get('id')}-completed", source="signed_via_documenso",
    )
