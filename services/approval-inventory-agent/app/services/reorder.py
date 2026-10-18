"""Reorder suggestions for hardware stock (BR-5).

Each item has a reorder point and a reorder quantity. Either can be set on
the item; when it isn't, a business-rule default (a % of the item's total
stock) is used. An item needs reordering when the stock left after serving
its backordered requests is at or below the reorder point. The suggestion
then covers three things, each shown in the explanation:

    owed     units backordered requests are waiting for beyond what's on the shelf
    top-up   units to bring the shelf back up to the reorder point
    order    one reorder quantity on top, so the next request doesn't trip it again
"""
import math
from collections import defaultdict

from sqlalchemy import select

from app.models import PurchaseRequest

POINT_PCT_FALLBACK = 20      # inventory.reorder_point_pct
QUANTITY_PCT_FALLBACK = 25   # inventory.reorder_quantity_pct


def rule_defaults() -> tuple[float, float]:
    from shared.rules_engine import get_rule
    return (float(get_rule("inventory.reorder_point_pct", fallback=POINT_PCT_FALLBACK)),
            float(get_rule("inventory.reorder_quantity_pct", fallback=QUANTITY_PCT_FALLBACK)))


def _pct_of(total: int, pct: float) -> int:
    return max(1, math.ceil(total * pct / 100))


def suggest(item, backordered: int, point_pct: float, quantity_pct: float) -> dict:
    """The reorder status of one inventory item (pure, no I/O)."""
    total, available = item.total_quantity or 0, item.available_quantity or 0
    point = item.reorder_point if item.reorder_point is not None else _pct_of(total, point_pct)
    quantity = item.reorder_quantity if item.reorder_quantity is not None else _pct_of(total, quantity_pct)
    owed = max(0, backordered - available)
    left = max(0, available - backordered)
    needs = left <= point
    top_up = max(0, point - left) if needs else 0
    suggested = owed + top_up + quantity if needs else 0

    shelf = f"{available} on the shelf"
    if backordered:
        shelf += f", {backordered} backordered → " + (f"{owed} owed" if owed else f"{left} left after backorders")
    if needs:
        parts = [f"{owed} owed"] if owed else []
        if top_up:
            parts.append(f"{top_up} to reach the reorder point ({point})")
        parts.append(f"{quantity} reorder quantity")
        explanation = f"{shelf}. Order " + " + ".join(parts) + f" = {suggested}."
    else:
        explanation = f"{shelf}; above the reorder point ({point})."
    return {
        "reorder_point": point,
        "reorder_quantity": quantity,
        "point_source": "item" if item.reorder_point is not None else "rule",
        "quantity_source": "item" if item.reorder_quantity is not None else "rule",
        "backordered_units": backordered,
        "needs_reorder": needs,
        "suggested_quantity": suggested,
        "explanation": explanation,
    }


async def backordered_by_sku(db) -> dict:
    """Units waiting on stock, per SKU, from backordered requests."""
    rows = (await db.execute(
        select(PurchaseRequest.items).where(PurchaseRequest.status == "backordered")
    )).scalars().all()
    units = defaultdict(int)
    for items in rows:
        for it in items or []:
            if it.get("sku"):
                units[it["sku"]] += int(it.get("quantity") or 0)
    return dict(units)


async def reorder_status(db, items: list) -> dict:
    """{item id: suggest(...)} for the given inventory items."""
    point_pct, quantity_pct = rule_defaults()
    waiting = await backordered_by_sku(db)
    return {str(i.id): suggest(i, waiting.get(i.sku, 0), point_pct, quantity_pct) for i in items}
