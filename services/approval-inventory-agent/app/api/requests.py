from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.config import settings
from app.schemas import CreatePurchaseRequest, ApprovalAction, PurchaseRequestResponse, DataResponse, ErrorResponse, ErrorDetail
from app.services.approval_service import ApprovalService
from shared.auth import require_role
from shared.idempotency import get_cached_response, store_response

router = APIRouter()

def get_approval_service(request: Request, db: AsyncSession = Depends(get_db)):
    producer = request.app.state.kafka_producer
    redis = request.app.state.redis
    return ApprovalService(db, producer, redis)

@router.post("/", response_model=DataResponse, dependencies=[Depends(require_role("requester", "admin"))])
async def create_request(
    data: CreatePurchaseRequest,
    request: Request,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    approval_svc: ApprovalService = Depends(get_approval_service)
):
    if idempotency_key:
        cached = await get_cached_response(request.app.state.redis, settings.service_name, idempotency_key)
        if cached is not None:
            return cached
    try:
        req = await approval_svc.create_request(data)
        result = DataResponse(data=PurchaseRequestResponse.model_validate(req))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    if idempotency_key:
        await store_response(request.app.state.redis, settings.service_name, idempotency_key, result.model_dump(mode="json"))
    return result

@router.get("/{request_id}", response_model=DataResponse)
async def get_request(
    request_id: str,
    approval_svc: ApprovalService = Depends(get_approval_service)
):
    req = await approval_svc.get_request_with_history(request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    return DataResponse(data=PurchaseRequestResponse.model_validate(req))

@router.post(
    "/{request_id}/approve", response_model=DataResponse,
    dependencies=[Depends(require_role("approver", "finance", "admin"))],
)
async def approve_request(
    request_id: str,
    action: ApprovalAction,
    approval_svc: ApprovalService = Depends(get_approval_service)
):
    try:
        req = await approval_svc.process_decision(request_id, "approved", action)
        return DataResponse(data=PurchaseRequestResponse.model_validate(req))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post(
    "/{request_id}/reject", response_model=DataResponse,
    dependencies=[Depends(require_role("approver", "finance", "admin"))],
)
async def reject_request(
    request_id: str,
    action: ApprovalAction,
    approval_svc: ApprovalService = Depends(get_approval_service)
):
    try:
        req = await approval_svc.process_decision(request_id, "rejected", action)
        return DataResponse(data=PurchaseRequestResponse.model_validate(req))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
