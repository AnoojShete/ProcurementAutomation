from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas import (
    CreatePurchaseRequest, ApprovalAction, PurchaseRequestResponse,
    DataResponse, ErrorResponse, ErrorDetail
)
from app.config import settings
from app.schemas import CreatePurchaseRequest, ApprovalAction, PurchaseRequestResponse, DataResponse, ErrorResponse, ErrorDetail
from app.services.approval_service import ApprovalService
from shared.auth import require_role
from shared.idempotency import get_cached_response, store_response

router = APIRouter()


def _error(code: str, message: str, status_code: int) -> JSONResponse:
    """Return a shared-contract error envelope."""
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(error=ErrorDetail(code=code, message=message)).model_dump()
    )


def get_approval_service(request: Request, db: AsyncSession = Depends(get_db)):
    producer = request.app.state.kafka_producer
    redis = request.app.state.redis
    return ApprovalService(db, producer, redis)


@router.post("/", response_model=DataResponse)
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
        return DataResponse(data=PurchaseRequestResponse.model_validate(req))
    except ValueError as e:
        return _error("VALIDATION_ERROR", str(e), 400)
        result = DataResponse(data=PurchaseRequestResponse.model_validate(req))
    except Exception as e:
        return _error("INTERNAL_ERROR", str(e), 500)

        raise HTTPException(status_code=400, detail=str(e))
    if idempotency_key:
        await store_response(request.app.state.redis, settings.service_name, idempotency_key, result.model_dump(mode="json"))
    return result

@router.get("/", response_model=DataResponse)
async def list_requests(
    limit: int = 100,
    approval_svc: ApprovalService = Depends(get_approval_service)
):
    """All purchase requests, most recent first — backs the tracking dashboard."""
    reqs = await approval_svc.list_requests(limit=limit)
    return DataResponse(
        data=[PurchaseRequestResponse.model_validate(r) for r in reqs],
        meta={"count": len(reqs)},
    )

@router.get("/{request_id}", response_model=DataResponse)
async def get_request(
    request_id: str,
    approval_svc: ApprovalService = Depends(get_approval_service)
):
    req = await approval_svc.get_request_with_history(request_id)
    if not req:
        return _error("NOT_FOUND", f"Request {request_id} not found", 404)
    return DataResponse(data=PurchaseRequestResponse.model_validate(req))


@router.post("/{request_id}/approve", response_model=DataResponse)
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
        return _error("VALIDATION_ERROR", str(e), 400)
    except Exception as e:
        return _error("INTERNAL_ERROR", str(e), 500)


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
        return _error("VALIDATION_ERROR", str(e), 400)
    except Exception as e:
        return _error("INTERNAL_ERROR", str(e), 500)

@router.post(
    "/{request_id}/decline-reclaim", response_model=DataResponse,
    dependencies=[Depends(require_role("requester", "admin"))],
)
async def decline_reclaim(
    request_id: str,
    action: ApprovalAction,
    approval_svc: ApprovalService = Depends(get_approval_service)
):
    try:
        req = await approval_svc.decline_reclaim(request_id, action.decided_by)
        return DataResponse(data=PurchaseRequestResponse.model_validate(req))
    except ValueError as e:
        return _error("VALIDATION_ERROR", str(e), 400)
    except Exception as e:
        return _error("INTERNAL_ERROR", str(e), 500)
