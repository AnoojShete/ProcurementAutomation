"""IT catalog API (feature expansion Phase 3a), /catalog.

Everyone signed in reads the available items (requesters order from it);
finance and admin add, change and switch items off. Items are never
deleted: requests keep pointing at them.
"""
import uuid
from datetime import date, datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import AuditLog, CatalogItem, Inventory, License, Vendor
from app.schemas import DataResponse
from app.services.catalog_service import REQUEST_TYPE_BY_CATEGORY, is_available
from shared.auth import CurrentUser, get_current_user, require_role

router = APIRouter()
MANAGE = ("finance", "admin")


def _uuid(v: Optional[str]) -> Optional[str]:
    if v:
        uuid.UUID(v)
    return v or None


class CatalogIn(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    category: Literal["hardware", "software", "saas"]
    vendor_id: str
    contract_id: Optional[str] = None
    unit_price: float = Field(ge=0, lt=10_000_000_000, allow_inf_nan=False)
    spec: dict = Field(default_factory=dict)
    inventory_sku: Optional[str] = Field(default=None, max_length=100)
    license_id: Optional[str] = None
    lead_time_days: Optional[int] = Field(default=None, ge=0, le=365)
    warranty_months: Optional[int] = Field(default=None, ge=0, le=120)
    valid_until: Optional[date] = None

    @field_validator("vendor_id", "contract_id", "license_id")
    @classmethod
    def _ids(cls, v):
        return _uuid(v)


class CatalogPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    unit_price: Optional[float] = Field(default=None, ge=0, lt=10_000_000_000, allow_inf_nan=False)
    spec: Optional[dict] = None
    lead_time_days: Optional[int] = Field(default=None, ge=0, le=365)
    warranty_months: Optional[int] = Field(default=None, ge=0, le=120)
    valid_until: Optional[date] = None
    clear_valid_until: bool = False
    active: Optional[bool] = None


def serialize(c: CatalogItem, vendor_name: Optional[str] = None, today: Optional[date] = None) -> dict:
    return {
        "id": c.id, "sku": c.sku, "name": c.name, "category": c.category,
        "request_type": REQUEST_TYPE_BY_CATEGORY.get(c.category), "vendor_id": c.vendor_id, "vendor_name": vendor_name,
        "contract_id": c.contract_id, "unit_price": float(c.unit_price), "currency": c.currency, "spec": c.spec or {},
        "inventory_sku": c.inventory_sku, "license_id": c.license_id, "lead_time_days": c.lead_time_days,
        "warranty_months": c.warranty_months, "active": c.active,
        "valid_until": c.valid_until.isoformat() if c.valid_until else None,
        "available": is_available(c, today), "seat_addon": bool(c.license_id),
    }


async def _check_links(db: AsyncSession, data) -> None:
    if getattr(data, "vendor_id", None) and await db.get(Vendor, data.vendor_id) is None:
        raise HTTPException(status_code=422, detail={"code": "catalog_rejected", "message": "unknown vendor"})
    if getattr(data, "license_id", None):
        lic = await db.get(License, data.license_id)
        if lic is None:
            raise HTTPException(status_code=422, detail={"code": "catalog_rejected", "message": "unknown licence"})
        if data.category == "hardware":
            raise HTTPException(status_code=422, detail={"code": "catalog_rejected",
                                                         "message": "seat add-ons are software or SaaS items"})
    if getattr(data, "inventory_sku", None):
        if (await db.execute(select(Inventory.id).where(Inventory.sku == data.inventory_sku))).first() is None:
            raise HTTPException(status_code=422, detail={"code": "catalog_rejected", "message": "no stock item with that SKU"})


@router.get("/", response_model=DataResponse)
async def list_items(q: Optional[str] = Query(None, max_length=100), category: Optional[str] = None,
                     include_unavailable: bool = False, db: AsyncSession = Depends(get_db),
                     user: CurrentUser = Depends(get_current_user)):
    """Available items; finance and admin can also see switched-off and expired ones."""
    stmt = select(CatalogItem, Vendor.name).outerjoin(Vendor, Vendor.id == CatalogItem.vendor_id)
    if category:
        stmt = stmt.where(CatalogItem.category == category)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(CatalogItem.name).like(like), func.lower(CatalogItem.sku).like(like)))
    today = date.today()
    if not (include_unavailable and user.role in MANAGE):
        stmt = stmt.where(CatalogItem.active.is_(True),
                          or_(CatalogItem.valid_until.is_(None), CatalogItem.valid_until >= today))
    rows = (await db.execute(stmt.order_by(CatalogItem.category, CatalogItem.name))).all()
    return DataResponse(data=[serialize(c, vname, today) for c, vname in rows])


@router.get("/{item_id}", response_model=DataResponse)
async def get_item(item_id: str, db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    try:
        uuid.UUID(item_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="catalog item not found")
    c = await db.get(CatalogItem, item_id)
    if c is None or (not is_available(c) and user.role not in MANAGE):
        raise HTTPException(status_code=404, detail="catalog item not found")
    vendor = await db.get(Vendor, c.vendor_id) if c.vendor_id else None
    return DataResponse(data=serialize(c, vendor.name if vendor else None))


@router.post("/", response_model=DataResponse, status_code=201)
async def create_item(data: CatalogIn, db: AsyncSession = Depends(get_db),
                      user: CurrentUser = Depends(require_role(*MANAGE))):
    await _check_links(db, data)
    now = datetime.now(timezone.utc)
    c = CatalogItem(id=str(uuid.uuid4()), **data.model_dump(), currency="INR", active=True, created_by=user.email,
                    created_at=now, updated_at=now)
    db.add(c)
    db.add(AuditLog(id=str(uuid.uuid4()), entity_type="catalog_item", entity_id=c.id, action="catalog_item_created",
                    performed_by=user.email, created_at=now,
                    details={"sku": c.sku, "unit_price": data.unit_price, "vendor_id": data.vendor_id}))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail={"code": "catalog_duplicate", "message": f"SKU {data.sku} already exists"})
    await db.refresh(c)
    return DataResponse(data=serialize(c))


@router.patch("/{item_id}", response_model=DataResponse)
async def update_item(item_id: str, data: CatalogPatch, db: AsyncSession = Depends(get_db),
                      user: CurrentUser = Depends(require_role(*MANAGE))):
    try:
        uuid.UUID(item_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="catalog item not found")
    c = await db.get(CatalogItem, item_id)
    if c is None:
        raise HTTPException(status_code=404, detail="catalog item not found")
    changes = {}
    for k, v in data.model_dump(exclude_unset=True, exclude={"clear_valid_until"}).items():
        old = getattr(c, k)
        if v is not None and v != old:
            changes[k] = {"from": str(old) if old is not None else None, "to": str(v)}
            setattr(c, k, v)
    if data.clear_valid_until and c.valid_until is not None:
        changes["valid_until"] = {"from": c.valid_until.isoformat(), "to": None}
        c.valid_until = None
    now = datetime.now(timezone.utc)
    c.updated_at = now
    if changes:
        db.add(AuditLog(id=str(uuid.uuid4()), entity_type="catalog_item", entity_id=c.id, action="catalog_item_updated",
                        performed_by=user.email, created_at=now, details=changes))
    await db.commit()
    await db.refresh(c)
    return DataResponse(data=serialize(c))
