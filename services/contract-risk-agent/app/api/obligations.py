"""Contract obligations API (feature expansion Phase 2), mounted under
/contracts next to the contract endpoints.

Read: whoever may see the contract (staff, or the requester of its purchase
request). Confirm, add, re-read and settle credits: finance, admin. Record
an outcome (met, waived, breach, downtime): approver, finance, admin — the
IT owner of a SaaS tool is usually an approver.
"""
import math
import uuid
from datetime import date, datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Contract, ContractObligation, ObligationEvent, SlaCredit
from app.schemas import DataResponse
from app.services import obligation_extraction as ox
from app.services import obligation_service as svc
from app.api.contracts import STAFF_ROLES, _visible_contract
from shared.auth import CurrentUser, get_current_user, require_role

router = APIRouter()
SETTLE = ("finance", "admin")
RECORD = ("approver", "finance", "admin")


class ConfirmIn(BaseModel):
    value: Optional[dict] = None
    owner_email: Optional[str] = Field(default=None, max_length=255)
    license_id: Optional[str] = None
    due_date: Optional[date] = None

    @field_validator("license_id")
    @classmethod
    def _uuid(cls, v):
        if v:
            uuid.UUID(v)
        return v


class ManualIn(ConfirmIn):
    type: str
    clause_text: Optional[str] = Field(default=None, max_length=4000)

    @field_validator("type")
    @classmethod
    def _type(cls, v):
        if v not in ox.TYPES:
            raise ValueError(f"type must be one of {', '.join(ox.TYPES)}")
        return v


class ActionIn(BaseModel):
    action: Literal["met", "waived", "reopened", "breach"]
    note: Optional[str] = Field(default=None, max_length=1000)


class DowntimeIn(BaseModel):
    period: str = Field(pattern=r"^\d{4}-\d{2}$")
    measured_uptime_pct: float
    note: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("measured_uptime_pct")
    @classmethod
    def _finite(cls, v):
        if not math.isfinite(v):
            raise ValueError("uptime must be a number")
        return v


class CreditIn(BaseModel):
    status: Literal["expected", "applied", "waived"]
    note: Optional[str] = Field(default=None, max_length=1000)


def _iso(v):
    return v.isoformat() if v else None


def serialize(ob: ContractObligation, events: list[ObligationEvent] = ()) -> dict:
    return {
        "id": ob.id, "contract_id": ob.contract_id, "type": ob.type, "label": ox.TYPES[ob.type].label,
        "clause_text": ob.clause_text, "value": ob.value or {}, "status": ob.status,
        "due_date": _iso(ob.due_date), "recurrence": ob.recurrence, "owner_email": ob.owner_email,
        "license_id": ob.license_id, "extracted_by": ob.extracted_by,
        "confidence": float(ob.confidence) if ob.confidence is not None else None,
        "confirmed_by": ob.confirmed_by, "confirmed_at": _iso(ob.confirmed_at),
        "events": [{"kind": e.kind, "details": e.details, "performed_by": e.performed_by,
                    "created_at": _iso(e.created_at)} for e in events],
    }


def credit_dict(c: SlaCredit) -> dict:
    return {"id": c.id, "obligation_id": c.obligation_id, "period": c.period,
            "measured_uptime_pct": float(c.measured_uptime_pct), "credit_pct": float(c.credit_pct),
            "credit_amount": float(c.credit_amount), "currency": c.currency, "status": c.status,
            "recorded_by": c.recorded_by, "resolved_by": c.resolved_by, "resolved_at": _iso(c.resolved_at),
            "note": c.note, "created_at": _iso(c.created_at)}


async def _obligation(db: AsyncSession, obligation_id: str) -> ContractObligation:
    try:
        uuid.UUID(obligation_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="obligation not found")
    ob = await db.get(ContractObligation, obligation_id)
    if ob is None:
        raise HTTPException(status_code=404, detail="obligation not found")
    return ob


async def _events(db: AsyncSession, ids: list[str]) -> dict[str, list]:
    out = {i: [] for i in ids}
    if ids:
        rows = (await db.execute(select(ObligationEvent).where(ObligationEvent.obligation_id.in_(ids))
                                 .order_by(ObligationEvent.created_at.desc()))).scalars().all()
        for e in rows:
            if len(out[e.obligation_id]) < 10:
                out[e.obligation_id].append(e)
    return out


def _fail(e: svc.ObligationError):
    raise HTTPException(status_code=422, detail={"code": "obligation_rejected", "message": str(e)})


async def _one(db: AsyncSession, ob: ContractObligation) -> DataResponse:
    await db.commit()
    await db.refresh(ob)
    return DataResponse(data=serialize(ob, (await _events(db, [ob.id]))[ob.id]))


@router.get("/obligations/types", response_model=DataResponse)
async def obligation_types(_: CurrentUser = Depends(get_current_user)):
    return DataResponse(data=[{"type": k, "label": t.label, "recurrence": t.recurrence,
                               "uses_model": k in ox.MODEL_TYPES} for k, t in ox.TYPES.items()])


@router.get("/obligations/by-license/{license_id}", response_model=DataResponse)
async def obligations_for_license(license_id: str, db: AsyncSession = Depends(get_db),
                                  user: CurrentUser = Depends(get_current_user)):
    """Confirmed licence limits and minimum commitments linked to a licence
    (the licence page shows them)."""
    if user.role not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="staff only")
    try:
        uuid.UUID(license_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="licence not found")
    rows = (await db.execute(select(ContractObligation).where(
        ContractObligation.license_id == license_id,
        ContractObligation.status.in_(["open", "breached", "met"])))).scalars().all()
    return DataResponse(data=[serialize(o) for o in rows])


@router.get("/{contract_id}/obligations", response_model=DataResponse)
async def list_obligations(contract_id: str, db: AsyncSession = Depends(get_db),
                           user: CurrentUser = Depends(get_current_user)):
    contract = await _visible_contract(db, contract_id, user)
    obs = (await db.execute(select(ContractObligation).where(ContractObligation.contract_id == contract_id)
                            .order_by(ContractObligation.created_at))).scalars().all()
    events = await _events(db, [o.id for o in obs])
    credits = (await db.execute(select(SlaCredit).where(SlaCredit.contract_id == contract_id)
                                .order_by(SlaCredit.period.desc()))).scalars().all()
    order = list(ox.TYPES)
    return DataResponse(data={
        "obligations": [serialize(o, events[o.id]) for o in sorted(obs, key=lambda o: order.index(o.type))],
        "credits": [credit_dict(c) for c in credits],
        "extracted_at": _iso(contract.obligations_extracted_at),
        "reading": contract.status == "signed" and contract.obligations_extracted_at is None,
    })


@router.post("/{contract_id}/obligations", response_model=DataResponse, status_code=201)
async def add_obligation(contract_id: str, data: ManualIn, db: AsyncSession = Depends(get_db),
                         user: CurrentUser = Depends(require_role(*SETTLE))):
    contract = await _visible_contract(db, contract_id, user)
    if contract.status != "signed":
        raise HTTPException(status_code=422, detail={"code": "obligation_rejected",
                                                     "message": "obligations are added to signed contracts"})
    now = datetime.now(timezone.utc)
    ob = ContractObligation(id=str(uuid.uuid4()), contract_id=contract_id, type=data.type,
                            clause_text=data.clause_text, value=data.value or {}, status="to_confirm",
                            recurrence=ox.TYPES[data.type].recurrence, extracted_by="manual",
                            created_at=now, updated_at=now)
    db.add(ob)
    await db.flush()
    try:
        await svc.confirm(db, ob, user.email, owner_email=data.owner_email, license_id=data.license_id,
                          due_date=data.due_date)
    except svc.ObligationError as e:
        await db.rollback()
        _fail(e)
    return await _one(db, ob)


@router.post("/{contract_id}/obligations/extract", response_model=DataResponse)
async def reread(contract_id: str, db: AsyncSession = Depends(get_db),
                 user: CurrentUser = Depends(require_role(*SETTLE))):
    """Read the contract again; adds only types it doesn't have yet."""
    contract = await _visible_contract(db, contract_id, user)
    if contract.status != "signed":
        raise HTTPException(status_code=422, detail={"code": "obligation_rejected",
                                                     "message": "obligations are read from signed contracts"})
    created = await svc.extract_for_contract(db, contract, actor=user.email)
    await db.commit()
    return DataResponse(data={"added": [o.type for o in created]})


@router.patch("/obligations/{obligation_id}/confirm", response_model=DataResponse)
async def confirm_obligation(obligation_id: str, data: ConfirmIn, db: AsyncSession = Depends(get_db),
                             user: CurrentUser = Depends(require_role(*SETTLE))):
    ob = await _obligation(db, obligation_id)
    try:
        await svc.confirm(db, ob, user.email, value=data.value, owner_email=data.owner_email,
                          license_id=data.license_id, due_date=data.due_date)
    except svc.ObligationError as e:
        _fail(e)
    return await _one(db, ob)


@router.post("/obligations/{obligation_id}/actions", response_model=DataResponse)
async def obligation_action(obligation_id: str, data: ActionIn, db: AsyncSession = Depends(get_db),
                            user: CurrentUser = Depends(require_role(*RECORD))):
    ob = await _obligation(db, obligation_id)
    if data.action in ("waived", "reopened") and user.role not in SETTLE:
        raise HTTPException(status_code=403, detail="finance or admin waives and reopens obligations")
    try:
        await svc.record(db, ob, data.action, user.email, data.note)
    except svc.ObligationError as e:
        _fail(e)
    return await _one(db, ob)


@router.post("/obligations/{obligation_id}/downtime", response_model=DataResponse)
async def record_downtime(obligation_id: str, data: DowntimeIn, db: AsyncSession = Depends(get_db),
                          user: CurrentUser = Depends(require_role(*RECORD))):
    ob = await _obligation(db, obligation_id)
    try:
        credit = await svc.record_downtime(db, ob, data.period, data.measured_uptime_pct, user.email, data.note)
    except svc.ObligationError as e:
        _fail(e)
    out = await _one(db, ob)
    return DataResponse(data={**out.data, "credit": credit_dict(credit) if credit else None})


@router.post("/sla-credits/{credit_id}", response_model=DataResponse)
async def settle_credit(credit_id: str, data: CreditIn, db: AsyncSession = Depends(get_db),
                        user: CurrentUser = Depends(require_role(*SETTLE))):
    try:
        uuid.UUID(credit_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="credit not found")
    credit = await db.get(SlaCredit, credit_id)
    if credit is None:
        raise HTTPException(status_code=404, detail="credit not found")
    try:
        await svc.resolve_credit(db, credit, data.status, user.email, data.note)
    except svc.ObligationError as e:
        _fail(e)
    await db.commit()
    return DataResponse(data=credit_dict(credit))
