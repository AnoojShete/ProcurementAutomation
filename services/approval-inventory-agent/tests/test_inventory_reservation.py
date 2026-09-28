"""reserve_stock holds the Redis lock only while it updates the database.
It used to keep the lock (keyed by SKU, 5-minute TTL) after a successful
reservation, so a second order for a well-stocked SKU looked out of stock
until it expired. Fix ported from the old `first` branch (Sep 28)."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.inventory_service import release_reservation, reserve_stock


class FakeRedis:
    def __init__(self):
        self.data = {}

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.data:
            return None
        self.data[key] = value
        return True

    async def eval(self, script, numkeys, key, value):  # the lock's compare-and-delete
        if self.data.get(key) == value:
            del self.data[key]
            return 1
        return 0

    async def exists(self, key):
        return int(key in self.data)


def _db(item):
    db = AsyncMock()
    res = MagicMock()
    res.scalar_one_or_none.return_value = item
    db.execute.return_value = res
    return db


@pytest.mark.asyncio
async def test_two_orders_for_a_stocked_sku_both_reserve():
    item = SimpleNamespace(available_quantity=10, reserved_quantity=0)
    redis, db = FakeRedis(), _db(item)
    assert await reserve_stock(db, redis, "LAPTOP-1", "req-1", 2)
    assert await reserve_stock(db, redis, "LAPTOP-1", "req-2", 3)
    assert (item.available_quantity, item.reserved_quantity) == (5, 5)
    assert redis.data == {}  # no lock left behind


@pytest.mark.asyncio
async def test_lock_released_when_stock_is_short():
    item = SimpleNamespace(available_quantity=1, reserved_quantity=0)
    redis = FakeRedis()
    assert not await reserve_stock(_db(item), redis, "LAPTOP-1", "req-1", 2)
    assert redis.data == {}


@pytest.mark.asyncio
async def test_concurrent_holder_blocks_then_release_returns_stock():
    item = SimpleNamespace(available_quantity=4, reserved_quantity=0)
    redis, db = FakeRedis(), _db(item)
    redis.data["inventory:lock:LAPTOP-1"] = "someone-else"  # a reservation mid-update
    assert not await reserve_stock(db, redis, "LAPTOP-1", "req-1", 1)
    del redis.data["inventory:lock:LAPTOP-1"]
    assert await reserve_stock(db, redis, "LAPTOP-1", "req-1", 3)
    assert await release_reservation(db, redis, "LAPTOP-1", "req-1", 3)
    assert (item.available_quantity, item.reserved_quantity) == (4, 0)
