"""Budgets per department, IT category and fiscal period (feature expansion
Phase 1). Usage is computed, not stored: see app/services/budget_service.py.

Read: approver, finance, admin (requesters see their own request's budget
line through GET /requests/{id}/budget). Write: finance, admin.
"""
import math
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import AuditLog, Budget
from app.schemas import DataResponse
from app.services import budget_service
from shared.auth import CurrentUser, require_role

router = APIRouter()

READ_ROLES = ("approver", "finance", "admin")
WRITE_ROLES = ("finance", "admin")
_FY = re.compile(r"^\d{4}-\d{2}$")


class BudgetIn(BaseModel):
    department: str = Field(min_length=1, max_length=255)
    category: str
    amount_inr: float = Field(ge=0)
    fiscal_year: Optional[str] = None   # default: the current fiscal year
    period: Optional[str] = None        # default: the current period
    owner_email: Optional[str] = Field(default=None, max_length=255)

    @field_validator("category")
    @classmethod
    def _category(cls, v):
        if v not in budget_service.CATEGORIES:
            raise ValueError(f"category must be one of {', '.join(budget_service.CATEGORIES)}")
        return v

    @field_validator("amount_inr")
    @classmethod
    def _finite(cls, v):
        if not math.isfinite(v):
            raise ValueError("amount must be a finite number")
        return v

    @field_validator("fiscal_year")
    @classmethod
    def _fy(cls, v):
        if v is not None and not _FY.match(v):
            raise ValueError("fiscal_year looks like 2026-27")
        return v

    @field_validator("period")
    @classmethod
    def _period(cls, v):
        if v is not None and v not in ("Q1", "Q2", "Q3", "Q4", "FY"):
            raise ValueError("period is Q1, Q2, Q3, Q4 or FY")
        return v


class BudgetPatch(BaseModel):
    amount_inr: Optional[float] = Field(default=None, ge=0)
    owner_email: Optional[str] = Field(default=None, max_length=255)

    @field_validator("amount_inr")
    @classmethod
    def _finite(cls, v):
        if v is not None and not math.isfinite(v):
            raise ValueError("amount must be a finite number")
        return v


class BudgetImport(BaseModel):
    rows: list[BudgetIn] = Field(max_length=1000)


def _scope(data: BudgetIn) -> tuple[str, str]:
    fiscal_year, period = budget_service.fiscal_period(datetime.now(timezone.utc))
    period_type = "FY" if period == "FY" else "Q"
    chosen = data.period or period
    if (chosen == "FY") != (period_type == "FY"):
        raise HTTPException(status_code=422, detail={
            "code": "period_mismatch",
            "message": f"Budgets are {'annual' if period_type == 'FY' else 'quarterly'} "
                       f"(rule budget.fiscal_period_type); use {'FY' if period_type == 'FY' else 'Q1-Q4'}."})
    return data.fiscal_year or fiscal_year, chosen


def _audit(db: AsyncSession, budget_id: str, action: str, user: CurrentUser, details: dict):
    db.add(AuditLog(id=str(uuid.uuid4()), entity_type="budget", entity_id=budget_id, action=action,
                    performed_by=user.email, details=details, created_at=datetime.now(timezone.utc)))


async def _get(db: AsyncSession, budget_id: str) -> Budget:
    try:
        uuid.UUID(budget_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="budget not found")
    budget = await db.get(Budget, budget_id)
    if budget is None:
        raise HTTPException(status_code=404, detail="budget not found")
    return budget


@router.get("/period", response_model=DataResponse, dependencies=[Depends(require_role(*READ_ROLES))])
async def current_period():
    fiscal_year, period = budget_service.fiscal_period(datetime.now(timezone.utc))
    return DataResponse(data={"fiscal_year": fiscal_year, "period": period,
                              "period_type": "annual" if period == "FY" else "quarterly",
                              "categories": list(budget_service.CATEGORIES)})


@router.get("/", response_model=DataResponse, dependencies=[Depends(require_role(*READ_ROLES))])
async def list_budgets(
    fiscal_year: Optional[str] = Query(None),
    period: Optional[str] = Query(None),
    department: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Budget)
    if fiscal_year:
        stmt = stmt.where(Budget.fiscal_year == fiscal_year)
    if period:
        stmt = stmt.where(Budget.period == period)
    if department:
        stmt = stmt.where(func.lower(Budget.department) == department.lower())
    budgets = list((await db.execute(stmt.order_by(Budget.fiscal_year.desc(), Budget.period, Budget.department,
                                                   Budget.category))).scalars().all())
    used = await budget_service.usage(db, [str(b.id) for b in budgets])
    rows = [budget_service.summarise(b, used[str(b.id)]) for b in budgets]
    totals = {k: round(sum(r[k] for r in rows), 2) for k in ("amount_inr", "consumed", "committed", "pending", "left")}
    return DataResponse(data=rows, meta={"count": len(rows), "totals": totals})


@router.post("/", response_model=DataResponse, status_code=201)
async def create_budget(data: BudgetIn, db: AsyncSession = Depends(get_db),
                        user: CurrentUser = Depends(require_role(*WRITE_ROLES))):
    fiscal_year, period = _scope(data)
    if await budget_service.find_budget(db, fiscal_year, period, data.department, data.category):
        raise HTTPException(status_code=409, detail={
            "code": "budget_exists",
            "message": f"A {data.category} budget for {data.department} in {period} {fiscal_year} already exists."})
    budget = Budget(id=str(uuid.uuid4()), fiscal_year=fiscal_year, period=period, department=data.department.strip(),
                    category=data.category, amount_inr=data.amount_inr, owner_email=data.owner_email,
                    created_by=user.email)
    db.add(budget)
    _audit(db, budget.id, "budget_created", user, {"fiscal_year": fiscal_year, "period": period,
                                                     "department": budget.department, "category": data.category,
                                                     "amount_inr": data.amount_inr})
    await db.commit()
    used = await budget_service.usage(db, [budget.id])
    return DataResponse(data=budget_service.summarise(budget, used[budget.id]))


@router.get("/{budget_id}", response_model=DataResponse, dependencies=[Depends(require_role(*READ_ROLES))])
async def get_budget(budget_id: str, db: AsyncSession = Depends(get_db)):
    budget = await _get(db, budget_id)
    used = await budget_service.usage(db, [budget_id])
    rows = (await db.execute(text(
        "SELECT pr.id, pr.request_type, pr.status, pr.amount, pr.requested_by, pr.created_at, pr.budget_status, "
        "COALESCE((SELECT SUM(a.amount) FROM invoice_allocations a WHERE a.purchase_request_id = pr.id), 0) AS invoiced "
        "FROM purchase_requests pr WHERE pr.budget_id = :b ORDER BY pr.created_at DESC"
    ), {"b": budget_id})).mappings().all()
    requests = [{"id": str(r["id"]), "request_type": r["request_type"], "status": r["status"],
                 "amount": float(r["amount"]), "invoiced": float(r["invoiced"]), "requested_by": r["requested_by"],
                 "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                 "budget_status_at_creation": r["budget_status"],
                 "counts_as": ("consumed/committed" if r["status"] in budget_service.USED_STATUSES
                               else "pending" if r["status"] in budget_service.PENDING_STATUSES else "released")}
                for r in rows]
    return DataResponse(data={**budget_service.summarise(budget, used[budget_id]), "requests": requests})


@router.patch("/{budget_id}", response_model=DataResponse)
async def update_budget(budget_id: str, data: BudgetPatch, db: AsyncSession = Depends(get_db),
                        user: CurrentUser = Depends(require_role(*WRITE_ROLES))):
    budget = await _get(db, budget_id)
    changes = {}
    if data.amount_inr is not None and float(budget.amount_inr) != data.amount_inr:
        changes["amount_inr"] = {"from": float(budget.amount_inr), "to": data.amount_inr}
        budget.amount_inr = data.amount_inr
    if data.owner_email is not None and data.owner_email != budget.owner_email:
        changes["owner_email"] = {"from": budget.owner_email, "to": data.owner_email}
        budget.owner_email = data.owner_email or None
    if changes:
        budget.updated_at = datetime.now(timezone.utc)
        _audit(db, budget.id, "budget_updated", user, changes)
        await db.commit()
    used = await budget_service.usage(db, [budget_id])
    return DataResponse(data=budget_service.summarise(budget, used[budget_id]))


@router.delete("/{budget_id}", response_model=DataResponse)
async def delete_budget(budget_id: str, db: AsyncSession = Depends(get_db),
                        user: CurrentUser = Depends(require_role(*WRITE_ROLES))):
    budget = await _get(db, budget_id)
    in_use = (await db.execute(text("SELECT count(*) FROM purchase_requests WHERE budget_id = :b"),
                               {"b": budget_id})).scalar()
    if in_use:
        raise HTTPException(status_code=409, detail={
            "code": "budget_in_use",
            "message": f"{in_use} request(s) draw on this budget; change its amount instead of deleting it."})
    _audit(db, budget.id, "budget_deleted", user, {"department": budget.department, "category": budget.category,
                                                     "period": budget.period, "fiscal_year": budget.fiscal_year})
    await db.delete(budget)
    await db.commit()
    return DataResponse(data={"deleted": budget_id})


@router.post("/import", response_model=DataResponse)
async def import_budgets(data: BudgetImport, db: AsyncSession = Depends(get_db),
                         user: CurrentUser = Depends(require_role(*WRITE_ROLES))):
    """Creates the budgets that don't exist and updates the amount (and owner)
    of the ones that do. All rows or none."""
    created = updated = 0
    for row in data.rows:
        fiscal_year, period = _scope(row)
        existing = await budget_service.find_budget(db, fiscal_year, period, row.department, row.category)
        if existing:
            if float(existing.amount_inr) != row.amount_inr or (row.owner_email and row.owner_email != existing.owner_email):
                _audit(db, existing.id, "budget_updated", user,
                       {"amount_inr": {"from": float(existing.amount_inr), "to": row.amount_inr}, "source": "import"})
                existing.amount_inr = row.amount_inr
                existing.owner_email = row.owner_email or existing.owner_email
                existing.updated_at = datetime.now(timezone.utc)
                updated += 1
        else:
            budget = Budget(id=str(uuid.uuid4()), fiscal_year=fiscal_year, period=period,
                            department=row.department.strip(), category=row.category, amount_inr=row.amount_inr,
                            owner_email=row.owner_email, created_by=user.email)
            db.add(budget)
            await db.flush()  # a later row for the same scope updates this one
            _audit(db, budget.id, "budget_created", user, {"source": "import", "amount_inr": row.amount_inr})
            created += 1
    await db.commit()
    return DataResponse(data={"created": created, "updated": updated, "rows": len(data.rows)})
