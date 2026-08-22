from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas import CreatePurchaseRequest, ApprovalAction, PurchaseRequestResponse, DataResponse, ErrorResponse, ErrorDetail
from app.services.approval_service import ApprovalService

router = APIRouter()

def get_approval_service(request: Request, db: AsyncSession = Depends(get_db)):
    producer = request.app.state.kafka_producer
    redis = request.app.state.redis
    return ApprovalService(db, producer, redis)

@router.post("/", response_model=DataResponse)
async def create_request(
    data: CreatePurchaseRequest,
    approval_svc: ApprovalService = Depends(get_approval_service)
):
    try:
        req = await approval_svc.create_request(data)
        return DataResponse(data=PurchaseRequestResponse.model_validate(req))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{request_id}", response_model=DataResponse)
async def get_request(
    request_id: str,
    approval_svc: ApprovalService = Depends(get_approval_service)
):
    req = await approval_svc.get_request_with_history(request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    return DataResponse(data=PurchaseRequestResponse.model_validate(req))

@router.post("/{request_id}/approve", response_model=DataResponse)
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

@router.post("/{request_id}/reject", response_model=DataResponse)
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
