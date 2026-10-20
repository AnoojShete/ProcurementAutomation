import logging
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas import (
    CreatePurchaseRequest, ApprovalAction, PurchaseRequestResponse,
    DataResponse, ErrorResponse, ErrorDetail
)
from app.config import settings
from app.schemas import CreatePurchaseRequest, ApprovalAction, PurchaseRequestResponse, DataResponse, ErrorResponse, ErrorDetail
from app.services.approval_service import ApprovalService
from shared.auth import CurrentUser, get_current_user, require_role

# Roles that work across everyone's requests; "service" is the internal
# token document-vendor-agent uses.
STAFF_ROLES = frozenset({"approver", "finance", "admin", "service"})
from app.services.approval_authority import AuthorityError
from shared.idempotency import get_cached_response, store_response

logger = logging.getLogger(__name__)

router = APIRouter()


def _error(code: str, message: str, status_code: int) -> JSONResponse:
    """Return a shared-contract error envelope."""
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(error=ErrorDetail(code=code, message=message)).model_dump()
    )


def _malformed_id(request_id: str) -> Optional[JSONResponse]:
    """The 400 every other endpoint returns for a non-UUID id (the shared DB
    error handler's response); approve/reject would otherwise turn the
    driver error into a generic 500."""
    try:
        uuid.UUID(request_id)
        return None
    except ValueError:
        return _error("bad_request", "malformed identifier or field value", 400)


def get_approval_service(request: Request, db: AsyncSession = Depends(get_db)):
    producer = request.app.state.kafka_producer
    redis = request.app.state.redis
    return ApprovalService(db, producer, redis)


@router.post("/", response_model=DataResponse)
async def create_request(
    data: CreatePurchaseRequest,
    request: Request,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    approval_svc: ApprovalService = Depends(get_approval_service),
    user: CurrentUser = Depends(require_role("requester", "admin")),
):
    # Identity comes from the JWT, never the body — otherwise any requester
    # could file requests (and pass SoD checks) as someone else.
    data = data.model_copy(update={"requested_by": user.email})
    if idempotency_key:
        cached = await get_cached_response(request.app.state.redis, settings.service_name, idempotency_key, scope=user.id)
        if cached is not None:
            return cached
    from app.services.budget_service import BudgetBlocked
    from app.services.catalog_service import CatalogError
    try:
        req = await approval_svc.create_request(data, document_id=data.document_id)
        result = DataResponse(data=PurchaseRequestResponse.model_validate(req))
    except (BudgetBlocked, CatalogError) as e:
        return _error(e.code, e.message, 422)
    except ValueError as e:
        return _error("VALIDATION_ERROR", str(e), 400)
    except Exception:
        logger.exception("create_request failed")
        return _error("INTERNAL_ERROR", "Failed to create purchase request", 500)
    if idempotency_key:
        await store_response(request.app.state.redis, settings.service_name, idempotency_key, result.model_dump(mode="json"), scope=user.id)
    return result

@router.get("/", response_model=DataResponse)
async def list_requests(
    limit: int = Query(100, ge=1, le=1000),
    approval_svc: ApprovalService = Depends(get_approval_service),
    user: CurrentUser = Depends(get_current_user),
):
    """Purchase requests, most recent first — backs the tracking dashboard.
    Requesters see only their own; approvers/finance/admin see all."""
    owner = None if user.role in STAFF_ROLES else user.email
    reqs = await approval_svc.list_requests(limit=limit, requested_by=owner)
    return DataResponse(
        data=[PurchaseRequestResponse.model_validate(r) for r in reqs],
        meta={"count": len(reqs)},
    )


@router.get("/search", response_model=DataResponse,
            dependencies=[Depends(require_role("service", "approver", "finance", "admin"))])
async def search_requests(
    vendor_id: Optional[str] = None,
    amount_min: Optional[float] = None,
    amount_max: Optional[float] = None,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select
    from app.models import PurchaseRequest
    query = select(PurchaseRequest)
    if vendor_id:
        query = query.where(PurchaseRequest.vendor_id == vendor_id)
    if status:
        query = query.where(PurchaseRequest.status == status)
    if amount_min is not None:
        query = query.where(PurchaseRequest.amount >= amount_min)
    if amount_max is not None:
        query = query.where(PurchaseRequest.amount <= amount_max)

    result = await db.execute(query)
    reqs = list(result.scalars().all())
    data = []
    for r in reqs:
        resp = PurchaseRequestResponse.model_validate(r)
        if not resp.po_number:
            resp.po_number = f"PO-{r.id[:8].upper()}"
        data.append(resp)
    return DataResponse(data=data, meta={"count": len(data)})


@router.get("/{request_id}", response_model=DataResponse)
async def get_request(
    request_id: str,
    approval_svc: ApprovalService = Depends(get_approval_service),
    user: CurrentUser = Depends(get_current_user),
):
    req = await approval_svc.get_request_with_history(request_id)
    # Someone else's request looks exactly like a missing one to a requester.
    if not req or (user.role not in STAFF_ROLES and req.requested_by.lower() != user.email.lower()):
        return _error("NOT_FOUND", f"Request {request_id} not found", 404)
    return DataResponse(data=PurchaseRequestResponse.model_validate(req))


@router.get("/{request_id}/budget", response_model=DataResponse)
async def get_request_budget(
    request_id: str,
    approval_svc: ApprovalService = Depends(get_approval_service),
    user: CurrentUser = Depends(get_current_user),
):
    """The request's budget line: the check made when it was created and
    the budget as it stands now. Same visibility as the request itself."""
    if (bad := _malformed_id(request_id)) is not None:
        return bad
    req = await approval_svc.get_request_with_history(request_id)
    if not req or (user.role not in STAFF_ROLES and req.requested_by.lower() != user.email.lower()):
        return _error("NOT_FOUND", f"Request {request_id} not found", 404)
    from app.models import Budget
    from app.services import budget_service
    current = None
    if req.budget_id:
        budget = await approval_svc.db.get(Budget, req.budget_id)
        if budget is not None:
            used = await budget_service.usage(approval_svc.db, [str(budget.id)])
            current = budget_service.summarise(budget, used[str(budget.id)])
    return DataResponse(data={
        "applies": budget_service.category_for(req.request_type) is not None,
        "status_at_creation": req.budget_status,
        "check": req.budget_check,
        "budget": current,
    })


@router.post("/{request_id}/approve", response_model=DataResponse)
async def approve_request(
    request_id: str,
    action: ApprovalAction,
    approval_svc: ApprovalService = Depends(get_approval_service),
    user: CurrentUser = Depends(require_role("approver", "finance", "admin")),
):
    if (bad := _malformed_id(request_id)) is not None:
        return bad
    action = action.model_copy(update={"decided_by": user.email})
    try:
        req = await approval_svc.process_decision(request_id, "approved", action)
        return DataResponse(data=PurchaseRequestResponse.model_validate(req))
    except AuthorityError as e:
        return _error(e.decision.code, str(e), 403)
    except ValueError as e:
        return _error("VALIDATION_ERROR", str(e), 400)
    except Exception:
        logger.exception("approve_request failed")
        return _error("INTERNAL_ERROR", "Failed to approve request", 500)


@router.post("/{request_id}/receive", response_model=DataResponse)
async def receive_request(
    request_id: str,
    approval_svc: ApprovalService = Depends(get_approval_service),
    user: CurrentUser = Depends(get_current_user),
):
    """The goods/licences arrived: ordered -> fulfilled, and licences are
    activated / stock released. The requester (it's their order) or staff."""
    from app.kafka.consumer import NotReceivable
    from app.services.receipt_service import ReceiptError, receive_all
    req = await approval_svc.get_request_with_history(request_id)
    if not req or (user.role not in STAFF_ROLES and req.requested_by.lower() != user.email.lower()):
        return _error("NOT_FOUND", f"Request {request_id} not found", 404)
    try:
        await receive_all(approval_svc.db, req, user.email, approval_svc.producer)
        await approval_svc.db.commit()
    except (NotReceivable, ReceiptError) as e:
        await approval_svc.db.rollback()
        return _error("NOT_RECEIVABLE", str(e), 409)
    req = await approval_svc.get_request_with_history(request_id)
    return DataResponse(data=PurchaseRequestResponse.model_validate(req))


class ReceiptLine(BaseModel):
    line_no: int = Field(ge=0)
    quantity: int = Field(ge=0)
    asset_tags: list[str] = Field(default_factory=list, max_length=500)


class ReceiptIn(BaseModel):
    lines: list[ReceiptLine] = Field(min_length=1, max_length=200)
    notes: Optional[str] = Field(default=None, max_length=1000)


def _receipt_dict(r) -> dict:
    return {"id": r.id, "lines": r.lines, "received_by": r.received_by,
            "received_at": r.received_at.isoformat() if r.received_at else None, "notes": r.notes}


@router.get("/{request_id}/receipts", response_model=DataResponse)
async def list_receipts(request_id: str, approval_svc: ApprovalService = Depends(get_approval_service),
                        user: CurrentUser = Depends(get_current_user)):
    """Deliveries so far and what is still to come, per line (Phase 3)."""
    from app.services import receipt_service
    if (bad := _malformed_id(request_id)) is not None:
        return bad
    req = await approval_svc.get_request_with_history(request_id)
    if not req or (user.role not in STAFF_ROLES and req.requested_by.lower() != user.email.lower()):
        return _error("NOT_FOUND", f"Request {request_id} not found", 404)
    receipts = await receipt_service.receipts_for(approval_svc.db, request_id)
    received = receipt_service.total_received(receipts)
    from app.services.invoice_ledger import po_lines_from_items
    return DataResponse(data={
        "receipts": [_receipt_dict(r) for r in receipts],
        "lines": [{"line_no": pl.line_no, "description": pl.description, "ordered": pl.quantity,
                   "received": received.get(pl.line_no, 0)} for pl in po_lines_from_items(req.items)],
    })


@router.post("/{request_id}/receipts", response_model=DataResponse, status_code=201)
async def record_receipt(request_id: str, data: ReceiptIn, approval_svc: ApprovalService = Depends(get_approval_service),
                         user: CurrentUser = Depends(get_current_user)):
    """One delivery: quantities per line, asset tags for hardware. The
    requester (it's their order) or staff."""
    from app.services.receipt_service import ReceiptError, record_receipt as record
    if (bad := _malformed_id(request_id)) is not None:
        return bad
    req = await approval_svc.get_request_with_history(request_id)
    if not req or (user.role not in STAFF_ROLES and req.requested_by.lower() != user.email.lower()):
        return _error("NOT_FOUND", f"Request {request_id} not found", 404)
    try:
        receipt, outcome = await record(approval_svc.db, req, [l.model_dump() for l in data.lines], user.email,
                                        approval_svc.producer, data.notes)
        await approval_svc.db.commit()
    except ReceiptError as e:
        await approval_svc.db.rollback()
        return _error("NOT_RECEIVABLE", str(e), 409)
    req = await approval_svc.get_request_with_history(request_id)
    return DataResponse(data={"receipt": _receipt_dict(receipt), "outcome": outcome,
                              "request": PurchaseRequestResponse.model_validate(req).model_dump(mode="json")})


@router.post("/{request_id}/reject", response_model=DataResponse)
async def reject_request(
    request_id: str,
    action: ApprovalAction,
    approval_svc: ApprovalService = Depends(get_approval_service),
    user: CurrentUser = Depends(require_role("approver", "finance", "admin")),
):
    if (bad := _malformed_id(request_id)) is not None:
        return bad
    action = action.model_copy(update={"decided_by": user.email})
    try:
        req = await approval_svc.process_decision(request_id, "rejected", action)
        return DataResponse(data=PurchaseRequestResponse.model_validate(req))
    except AuthorityError as e:
        return _error(e.decision.code, str(e), 403)
    except ValueError as e:
        return _error("VALIDATION_ERROR", str(e), 400)
    except Exception:
        logger.exception("reject_request failed")
        return _error("INTERNAL_ERROR", "Failed to reject request", 500)

@router.post("/{request_id}/decline-reclaim", response_model=DataResponse)
async def decline_reclaim(
    request_id: str,
    action: ApprovalAction,
    approval_svc: ApprovalService = Depends(get_approval_service),
    user: CurrentUser = Depends(require_role("requester", "admin")),
):
    action = action.model_copy(update={"decided_by": user.email})
    try:
        req = await approval_svc.decline_reclaim(request_id, action.decided_by)
        return DataResponse(data=PurchaseRequestResponse.model_validate(req))
    except ValueError as e:
        return _error("VALIDATION_ERROR", str(e), 400)
    except Exception:
        logger.exception("decline_reclaim failed")
        return _error("INTERNAL_ERROR", "Failed to decline reclaim", 500)
