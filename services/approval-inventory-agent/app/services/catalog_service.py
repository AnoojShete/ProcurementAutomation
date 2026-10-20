"""IT catalog (feature expansion Phase 3a).

A catalog item is an approved IT product or seat add-on with an agreed
price: a standard laptop, a monitor, a software title, more seats on a SaaS
tool the company already has. A requester picks items instead of typing
them, so the price, vendor and category are known before approval and the
budget check (Phase 1) and the spend tier are exact.

Requests reference items by `catalog_item_id`; create_request() calls
resolve_items() first, which fills in the agreed price, name, stock SKU and
licence, and refuses an item that is switched off or whose price has
expired (`valid_until`). An item with `inventory_sku` reserves stock like any
hardware line; one with `license_id` adds seats to that licence when the
request is received (consumer.apply_received).

Rules:
  catalog.preapproved_max_inr   catalog-only requests up to this amount skip
                                the manager step (0 = off)
"""
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.rules_engine import get_rule

REQUEST_TYPE_BY_CATEGORY = {"hardware": "hardware", "software": "license", "saas": "saas"}
MANAGER_LEVEL = "dept_manager"


class CatalogError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class CatalogResolution:
    items: list
    vendor_id: Optional[str]
    request_type: str
    amount: float
    all_catalog: bool
    flags: list = field(default_factory=list)


def is_available(item, today: Optional[date] = None) -> bool:
    today = today or date.today()
    return bool(item.active) and (item.valid_until is None or item.valid_until >= today)


async def contract_seat_limit(db: AsyncSession, license_id: str) -> Optional[int]:
    """The confirmed licence limit (contract-risk-agent's contract
    obligations, Phase 2) on this licence, or None."""
    try:
        async with db.begin_nested():
            row = (await db.execute(text(
                "SELECT min((value->>'seats')::int) FROM contract_obligations WHERE license_id = :l "
                "AND type = 'license_limit' AND status IN ('open', 'breached') AND value ? 'seats'"),
                {"l": str(license_id)})).first()
    except Exception:
        return None
    return int(row[0]) if row and row[0] else None


async def resolve_items(db: AsyncSession, items: Optional[list], today: Optional[date] = None) -> Optional[CatalogResolution]:
    """None when no line comes from the catalog. Otherwise the request's
    lines with catalog prices filled in, the vendor, type and amount."""
    from app.models import CatalogItem, License

    lines = items or []
    ids = [str(i["catalog_item_id"]) for i in lines if i.get("catalog_item_id")]
    if not ids:
        return None
    found = {c.id: c for c in (await db.execute(select(CatalogItem).where(CatalogItem.id.in_(ids)))).scalars().all()}
    out, vendors, types, flags, amount = [], set(), set(), [], 0.0
    for line in lines:
        cid = line.get("catalog_item_id")
        if not cid:
            # A free-text line next to catalog lines keeps its own price.
            out.append(line)
            amount += float(line.get("quantity") or 0) * float(line.get("unit_price") or 0)
            continue
        item = found.get(str(cid))
        if item is None or not is_available(item, today):
            name = item.name if item is not None else str(cid)
            raise CatalogError("catalog_unavailable",
                               f"{name} is no longer in the catalog (switched off or its agreed price expired)")
        qty = line.get("quantity", 1)
        if not isinstance(qty, int) or isinstance(qty, bool) or qty < 1:
            raise CatalogError("catalog_quantity", f"quantity for {item.name} must be a whole number of at least 1")
        price = float(item.unit_price)
        resolved = {
            "catalog_item_id": item.id, "name": item.name, "description": item.name, "quantity": qty,
            "unit_price": price, "category": "hardware" if item.category == "hardware" else "software",
            "catalog_sku": item.sku,
        }
        if item.inventory_sku:
            resolved["sku"] = item.inventory_sku
        if item.license_id:
            resolved["license_id"] = item.license_id
            resolved["seat_addon"] = True
            lic = await db.get(License, item.license_id)
            cap = await contract_seat_limit(db, item.license_id)
            if lic is not None and cap is not None and lic.total_seats + qty > cap:
                flags.append({"code": "over_contract_seats",
                              "message": f"{lic.app_name}: {lic.total_seats} + {qty} seats is more than the "
                                         f"{cap} the contract allows; the contract needs amending first"})
        for k in ("lead_time_days", "warranty_months"):
            if getattr(item, k) is not None:
                resolved[k] = getattr(item, k)
        out.append(resolved)
        amount += qty * price
        vendors.add(item.vendor_id)
        types.add(REQUEST_TYPE_BY_CATEGORY.get(item.category, "hardware"))
    if len(vendors) > 1:
        raise CatalogError("catalog_mixed_vendors", "catalog items from different vendors go in separate requests")
    if len(types) > 1:
        raise CatalogError("catalog_mixed_types", "hardware and software catalog items go in separate requests")
    return CatalogResolution(items=out, vendor_id=next(iter(vendors)), request_type=types.pop(), amount=round(amount, 2),
                             all_catalog=all(line.get("catalog_item_id") for line in out), flags=flags)


def preapproved(resolution: Optional[CatalogResolution]) -> bool:
    """Catalog-only and within catalog.preapproved_max_inr (0 = off)."""
    if resolution is None or not resolution.all_catalog:
        return False
    limit = float(get_rule("catalog.preapproved_max_inr", fallback=0) or 0)
    return limit > 0 and 0 < resolution.amount <= limit


def drop_manager_step(chain: list) -> list:
    """The manager step is what a pre-approved catalog price replaces;
    finance steps added by the budget or vendor-risk rules stay."""
    return [level for level in chain if level != MANAGER_LEVEL]
