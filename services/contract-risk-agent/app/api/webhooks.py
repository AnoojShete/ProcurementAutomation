from fastapi import APIRouter, Depends, HTTPException, Request
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
