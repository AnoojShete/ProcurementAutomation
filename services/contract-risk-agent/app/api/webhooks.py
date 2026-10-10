from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas import EsignWebhookPayload, DataResponse
from app.services import docusign_client, webhook_service

router = APIRouter()


@router.post("/esign", response_model=DataResponse)
async def esign_webhook(data: EsignWebhookPayload, request: Request, db: AsyncSession = Depends(get_db)):
    """Receives the signed-document callback from the e-sign provider.
    Not JWT-authenticated (the provider has no platform login) — trust is
    established by the HMAC signature instead. Exempt from the shared auth
    dependency in main.py for that reason."""
    try:
        contract = await webhook_service.handle_esign_webhook(db, request.app.state.kafka_producer, data.model_dump())
    except webhook_service.WebhookSignatureError:
        raise HTTPException(status_code=401, detail="invalid webhook signature")
    except webhook_service.WebhookReplayError:
        return DataResponse(data={"status": "already_processed"})
    except webhook_service.WebhookContractNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return DataResponse(data={"contract_id": contract.id, "status": contract.status})


@router.post("/documenso", response_model=DataResponse)
async def documenso_webhook(
    request: Request,
    x_documenso_secret: str | None = Header(None, alias="X-Documenso-Secret"),
    db: AsyncSession = Depends(get_db),
):
    """Documenso's webhook (configure it for DOCUMENT_COMPLETED, pointing
    at /api/webhooks/documenso, with APP_DOCUMENSO_WEBHOOK_SECRET as its
    secret). Marks the contract with that externalId as signed."""
    body = await request.json()
    try:
        contract = await webhook_service.handle_documenso_webhook(
            db, request.app.state.kafka_producer, body, x_documenso_secret
        )
    except webhook_service.WebhookSignatureError:
        raise HTTPException(status_code=401, detail="invalid webhook secret")
    except webhook_service.WebhookReplayError:
        return DataResponse(data={"status": "already_processed"})
    except webhook_service.WebhookContractNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if contract is None:
        return DataResponse(data={"status": "ignored", "event": body.get("event")})
    return DataResponse(data={"contract_id": contract.id, "status": contract.status})


@router.post("/docusign", response_model=DataResponse)
async def docusign_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """DocuSign Connect (JSON, HMAC on, "Envelope Completed" event), pointed
    at /api/webhooks/docusign with APP_DOCUSIGN_CONNECT_HMAC_KEY as its key.
    The payload only says which envelope changed: the envelope itself is
    read back from DocuSign before anything is marked signed. Optional — the
    status poller finds completed envelopes without it."""
    raw = await request.body()
    signatures = [v for k, v in request.headers.items() if k.lower().startswith("x-docusign-signature-")]
    if not docusign_client.verify_connect_signature(raw, signatures):
        raise HTTPException(status_code=401, detail="invalid DocuSign Connect signature")
    body = await request.json()
    env_id = (body.get("data") or {}).get("envelopeId")
    if not env_id or body.get("event") != "envelope-completed":
        return DataResponse(data={"status": "ignored", "event": body.get("event")})
    try:
        done = docusign_client.completion(await docusign_client.get_envelope(env_id))
    except docusign_client.DocuSignError as e:
        raise HTTPException(status_code=502, detail=str(e))
    if done is None:
        return DataResponse(data={"status": "ignored", "reason": "envelope not completed"})
    from sqlalchemy import select
    from app.models import Contract
    contract_id = (await db.execute(
        select(Contract.id).where(Contract.esign_provider_ref == f"{docusign_client.DOCUSIGN_REF_PREFIX}{env_id}")
    )).scalar_one_or_none()
    if contract_id is None:
        raise HTTPException(status_code=404, detail=f"no contract for DocuSign envelope {env_id}")
    signed_by, signed_at = done
    try:
        contract = await webhook_service.mark_contract_signed(
            db, request.app.state.kafka_producer, contract_id=str(contract_id), signed_by=signed_by,
            signed_at=signed_at, provider_event_id=f"docusign-{env_id}-completed", source="signed_via_docusign",
        )
    except webhook_service.WebhookReplayError:
        return DataResponse(data={"status": "already_processed"})
    return DataResponse(data={"contract_id": contract.id, "status": contract.status})
