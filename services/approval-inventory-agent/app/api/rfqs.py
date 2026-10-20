"""RFQ API (feature expansion Phase 3b), /rfqs.

Approvers, finance and admin see RFQs; finance and admin run them (issue,
record a quote, extend, close, next round, award, cancel). While an RFQ is
sealed and before its deadline, nobody — admins included — gets quote
amounts back: only which vendors have responded.
"""
import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import RfqEvent, Vendor
from app.schemas import DataResponse, PurchaseRequestResponse
from app.services import sourcing_service as svc
from shared.auth import CurrentUser, get_current_user, require_role

router = APIRouter()
VIEW = ("approver", "finance", "admin")
MANAGE = ("finance", "admin")


def _aware(v: datetime) -> datetime:
    return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


class RfqItem(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    quantity: int = Field(ge=1, le=100000)
    spec: Optional[str] = Field(default=None, max_length=1000)


class RfqIn(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    department: str = Field(min_length=1, max_length=255)
    request_type: Literal["hardware", "license", "saas"]
    items: list[RfqItem] = Field(min_length=1, max_length=100)
    vendor_ids: list[str] = Field(min_length=1, max_length=50)
    deadline: datetime
    sealed: bool = True
    criteria: Optional[dict] = None

    @field_validator("vendor_ids")
    @classmethod
    def _ids(cls, v):
        for x in v:
            uuid.UUID(x)
        return v


class ResponseIn(BaseModel):
    vendor_id: str
    total_inr: float = Field(gt=0, lt=10_000_000_000, allow_inf_nan=False)
    lead_time_days: Optional[int] = Field(default=None, ge=0, le=365)
    warranty_months: Optional[int] = Field(default=None, ge=0, le=120)
    support_rating: Optional[int] = Field(default=None, ge=1, le=5)
    support_terms: Optional[str] = Field(default=None, max_length=2000)
    line_items: list[dict] = Field(default_factory=list, max_length=200)

    @field_validator("vendor_id")
    @classmethod
    def _id(cls, v):
        uuid.UUID(v)
        return v


class DeadlineIn(BaseModel):
    deadline: datetime


class RoundIn(BaseModel):
    vendor_ids: list[str] = Field(min_length=1, max_length=50)
    deadline: datetime


class AwardIn(BaseModel):
    response_id: str


class CancelIn(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


def _fail(e: svc.SourcingError):
    raise HTTPException(status_code=e.status, detail={"code": e.code, "message": e.message})


async def _rfq(db: AsyncSession, rfq_id: str, lock: bool = False) -> RfqEvent:
    try:
        uuid.UUID(rfq_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="RFQ not found")
    stmt = select(RfqEvent).where(RfqEvent.id == rfq_id)
    rfq = (await db.execute(stmt.with_for_update() if lock else stmt)).scalars().first()
    if rfq is None:
        raise HTTPException(status_code=404, detail="RFQ not found")
    return rfq


def _iso(v):
    return v.isoformat() if v else None


def _summary(rfq: RfqEvent) -> dict:
    return {"id": rfq.id, "reference": rfq.reference, "title": rfq.title, "department": rfq.department,
            "request_type": rfq.request_type, "items": rfq.items, "criteria": rfq.criteria, "sealed": rfq.sealed,
            "round": rfq.round, "deadline": _iso(rfq.deadline), "status": rfq.status, "created_by": rfq.created_by,
            "awarded_vendor_id": rfq.awarded_vendor_id, "awarded_response_id": rfq.awarded_response_id,
            "awarded_request_id": rfq.awarded_request_id, "created_at": _iso(rfq.created_at)}


async def view(db: AsyncSession, rfq: RfqEvent) -> dict:
    """The RFQ with invitations and, once unsealed, quotes and scores."""
    invites = await svc.invitations(db, rfq.id)
    resps = await svc.responses(db, rfq.id)
    vendor_ids = {str(i.vendor_id) for i in invites}
    names = {str(v.id): v.name for v in (await db.execute(select(Vendor).where(Vendor.id.in_(vendor_ids)))).scalars().all()} if vendor_ids else {}
    sealed = svc.sealed_now(rfq)
    out = {**_summary(rfq), "sealed_now": sealed,
           "invitations": [{"vendor_id": i.vendor_id, "vendor_name": names.get(str(i.vendor_id)), "round": i.round,
                            "invited_at": _iso(i.invited_at), "responded_at": _iso(i.responded_at)} for i in invites]}
    if sealed:
        out["responses"] = [{"vendor_id": r.vendor_id, "vendor_name": names.get(str(r.vendor_id)), "round": r.round,
                             "submitted_at": _iso(r.submitted_at)} for r in resps]
        out["comparison"] = None
        return out
    full = [{"id": r.id, "vendor_id": r.vendor_id, "vendor_name": names.get(str(r.vendor_id)), "round": r.round,
             "total_inr": float(r.total_inr), "lead_time_days": r.lead_time_days, "warranty_months": r.warranty_months,
             "support_rating": r.support_rating, "support_terms": r.support_terms, "line_items": r.line_items,
             "source": r.source, "quote_id": r.quote_id, "submitted_at": _iso(r.submitted_at)} for r in resps]
    out["responses"] = full
    current = [r for r in full if r["round"] == rfq.round]
    info = await svc.vendor_info(db, [r["vendor_id"] for r in current])
    out["comparison"] = {"round": rfq.round, "weights": rfq.criteria, "vendor_info": info,
                         "ranked": svc.score(current, rfq.criteria, info)}
    return out


@router.get("/", response_model=DataResponse)
async def list_rfqs(status: Optional[str] = None, db: AsyncSession = Depends(get_db),
                    _: CurrentUser = Depends(require_role(*VIEW))):
    stmt = select(RfqEvent).order_by(RfqEvent.created_at.desc()).limit(200)
    if status:
        stmt = stmt.where(RfqEvent.status == status)
    rows = (await db.execute(stmt)).scalars().all()
    counts = {}
    for rfq in rows:
        inv = await svc.invitations(db, rfq.id, rfq.round)
        counts[rfq.id] = (len(inv), sum(1 for i in inv if i.responded_at))
    return DataResponse(data=[{**_summary(r), "invited": counts[r.id][0], "responded": counts[r.id][1]} for r in rows])


@router.get("/criteria", response_model=DataResponse)
async def criteria(_: CurrentUser = Depends(get_current_user)):
    return DataResponse(data={"criteria": list(svc.CRITERIA), "default": svc.default_criteria()})


@router.post("/", response_model=DataResponse, status_code=201)
async def create(data: RfqIn, request: Request, db: AsyncSession = Depends(get_db),
                 user: CurrentUser = Depends(require_role(*MANAGE))):
    try:
        rfq = await svc.create_rfq(db, request.app.state.kafka_producer, user.email, title=data.title,
                                   department=data.department.strip(), request_type=data.request_type,
                                   items=[i.model_dump() for i in data.items], vendor_ids=data.vendor_ids,
                                   deadline=_aware(data.deadline), sealed=data.sealed, criteria=data.criteria)
    except svc.SourcingError as e:
        await db.rollback()
        _fail(e)
    await db.commit()
    return DataResponse(data=await view(db, rfq))


@router.get("/{rfq_id}", response_model=DataResponse)
async def get_rfq(rfq_id: str, db: AsyncSession = Depends(get_db), _: CurrentUser = Depends(require_role(*VIEW))):
    rfq = await _rfq(db, rfq_id)
    if await svc.close_if_due(db, rfq):
        await db.commit()
    return DataResponse(data=await view(db, rfq))


async def _act(db: AsyncSession, rfq: RfqEvent, coro) -> DataResponse:
    try:
        await coro
    except svc.SourcingError as e:
        await db.rollback()
        _fail(e)
    await db.commit()
    await db.refresh(rfq)
    return DataResponse(data=await view(db, rfq))


@router.post("/{rfq_id}/responses", response_model=DataResponse)
async def record_response(rfq_id: str, data: ResponseIn, db: AsyncSession = Depends(get_db),
                          user: CurrentUser = Depends(require_role(*MANAGE))):
    rfq = await _rfq(db, rfq_id, lock=True)
    return await _act(db, rfq, svc.record_response(
        db, rfq, data.vendor_id, total_inr=data.total_inr, actor=user.email, lead_time_days=data.lead_time_days,
        warranty_months=data.warranty_months, support_rating=data.support_rating, support_terms=data.support_terms,
        line_items=data.line_items))


@router.post("/{rfq_id}/extend", response_model=DataResponse)
async def extend(rfq_id: str, data: DeadlineIn, db: AsyncSession = Depends(get_db),
                 user: CurrentUser = Depends(require_role(*MANAGE))):
    rfq = await _rfq(db, rfq_id, lock=True)
    return await _act(db, rfq, svc.extend(db, rfq, _aware(data.deadline), user.email))


@router.post("/{rfq_id}/close", response_model=DataResponse)
async def close(rfq_id: str, db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(require_role(*MANAGE))):
    rfq = await _rfq(db, rfq_id, lock=True)
    return await _act(db, rfq, svc.close(db, rfq, user.email))


@router.post("/{rfq_id}/rounds", response_model=DataResponse)
async def next_round(rfq_id: str, data: RoundIn, request: Request, db: AsyncSession = Depends(get_db),
                     user: CurrentUser = Depends(require_role(*MANAGE))):
    rfq = await _rfq(db, rfq_id, lock=True)
    return await _act(db, rfq, svc.next_round(db, request.app.state.kafka_producer, rfq, data.vendor_ids,
                                              _aware(data.deadline), user.email))


@router.post("/{rfq_id}/cancel", response_model=DataResponse)
async def cancel(rfq_id: str, data: CancelIn, db: AsyncSession = Depends(get_db),
                 user: CurrentUser = Depends(require_role(*MANAGE))):
    rfq = await _rfq(db, rfq_id, lock=True)
    return await _act(db, rfq, svc.cancel(db, rfq, user.email, data.reason))


@router.post("/{rfq_id}/award", response_model=DataResponse)
async def award(rfq_id: str, data: AwardIn, request: Request, db: AsyncSession = Depends(get_db),
                user: CurrentUser = Depends(require_role(*MANAGE))):
    """Creates the purchase request from the winning quote (budget check and
    approval as for any request; the awarding buyer is its requester)."""
    from app.services.approval_service import ApprovalService
    from app.services.budget_service import BudgetBlocked
    try:
        uuid.UUID(data.response_id)
    except ValueError:
        raise HTTPException(status_code=422, detail={"code": "rfq_rejected", "message": "unknown response"})
    rfq = await _rfq(db, rfq_id, lock=True)
    approval_svc = ApprovalService(db, request.app.state.kafka_producer, request.app.state.redis)
    try:
        req = await svc.award(db, approval_svc, request.app.state.kafka_producer, rfq, data.response_id, user.email)
    except svc.SourcingError as e:
        await db.rollback()
        _fail(e)
    except BudgetBlocked as e:
        await db.rollback()
        raise HTTPException(status_code=422, detail={"code": e.code, "message": e.message})
    await db.commit()
    await db.refresh(rfq)
    return DataResponse(data={**(await view(db, rfq)),
                              "request": PurchaseRequestResponse.model_validate(
                                  await approval_svc.get_request_with_history(req.id)).model_dump(mode="json")})
