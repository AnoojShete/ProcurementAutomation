from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas import EsignWebhookPayload, DataResponse
from app.services import webhook_service

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
