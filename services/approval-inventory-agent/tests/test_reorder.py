"""BR-5: reorder suggestions from stock + backorders, with the quantity
explained, using per-item settings or rule defaults."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.services.reorder import backordered_by_sku, suggest


def _item(total=20, available=12, point=None, quantity=None, sku="LAPTOP-1"):
    return SimpleNamespace(id="i1", sku=sku, total_quantity=total, available_quantity=available,
                           reorder_point=point, reorder_quantity=quantity)


def test_healthy_stock_needs_nothing():
    r = suggest(_item(total=20, available=12), 0, 20, 25)
    assert r["reorder_point"] == 4 and r["point_source"] == "rule"
    assert not r["needs_reorder"] and r["suggested_quantity"] == 0
    assert "above the reorder point (4)" in r["explanation"]


def test_backordered_item_gets_a_suggestion_with_the_quantity_explained():
    # 0 on the shelf, 5 owed to backordered requests, point 5, order qty 7
    r = suggest(_item(total=25, available=0), 5, 20, 25)
    assert r["needs_reorder"]
    assert r["suggested_quantity"] == 5 + 5 + 7
    assert r["explanation"] == (
        "0 on the shelf, 5 backordered → 5 owed. "
        "Order 5 owed + 5 to reach the reorder point (5) + 7 reorder quantity = 17."
    )


def test_backorders_count_against_the_shelf():
    # 6 on the shelf looks fine (point 4) but 4 are promised to a backorder
    r = suggest(_item(total=20, available=6), 4, 20, 25)
    assert r["needs_reorder"]
    assert "2 left after backorders" in r["explanation"]
    assert r["suggested_quantity"] == 0 + 2 + 5


def test_item_settings_override_the_rule():
    r = suggest(_item(total=20, available=3, point=2, quantity=10), 0, 20, 25)
    assert (r["reorder_point"], r["reorder_quantity"]) == (2, 10)
    assert r["point_source"] == "item" and r["quantity_source"] == "item"
    assert not r["needs_reorder"]
    r = suggest(_item(total=20, available=2, point=2, quantity=10), 0, 20, 25)
    assert r["needs_reorder"] and r["suggested_quantity"] == 10


def test_backordered_units_are_summed_per_sku():
    db = AsyncMock()
    res = MagicMock()
    res.scalars.return_value.all.return_value = [
        [{"sku": "DOCK-1", "quantity": 3}, {"sku": "MON-1", "quantity": 1}],
        [{"sku": "DOCK-1", "quantity": 2}, {"name": "no sku"}],
        None,
    ]
    db.execute.return_value = res
    loop = asyncio.new_event_loop()  # asyncio.run would unset the loop other tests use
    try:
        assert loop.run_until_complete(backordered_by_sku(db)) == {"DOCK-1": 5, "MON-1": 1}
    finally:
        loop.close()
