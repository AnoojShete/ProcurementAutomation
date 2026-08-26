"""Tests for Redis distributed lock.

The lock prevents two concurrent purchase requests from double-reserving
the same inventory stock.

Issue 8: The test_race_condition_two_concurrent_requests has been rewritten
to test the actual `reserve_stock` business function, not just the low-level
lock primitive. It simulates two requests competing for the same item with
only enough stock for one, verifying exactly one succeeds and exactly one
fails, with the correct remaining stock levels in the DB.
"""
import pytest
import asyncio
import sys
import os
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services.redis_lock import InventoryLock
from app.services.inventory_service import reserve_stock
from app.models import Inventory

@pytest.mark.asyncio
class TestRedisLock:
    """Test distributed locking for inventory reservation."""
    
    async def test_acquire_lock_success(self, mock_redis):
        """Should successfully acquire lock on unreserved resource."""
        mock_redis.set = AsyncMock(return_value=True)  # NX succeeds
        lock = InventoryLock(mock_redis, ttl=300)
        
        result = await lock.acquire("LAPTOP-DELL-5540", "token-123")
        assert result is True
        mock_redis.set.assert_called_once_with(
            "inventory:lock:LAPTOP-DELL-5540", "token-123", nx=True, ex=300
        )
    
    async def test_acquire_lock_already_held(self, mock_redis):
        """Should fail to acquire lock if already held by another request."""
        mock_redis.set = AsyncMock(return_value=None)  # NX fails
        lock = InventoryLock(mock_redis, ttl=300)
        
        result = await lock.acquire("LAPTOP-DELL-5540", "token-123")
        assert result is False
    
    async def test_release_lock_by_holder(self, mock_redis):
        """Should release lock when called by the holder."""
        mock_redis.eval = AsyncMock(return_value=1)  # Lua script succeeds
        lock = InventoryLock(mock_redis, ttl=300)
        
        result = await lock.release("LAPTOP-DELL-5540", "token-123")
        assert result is True
    
    async def test_release_lock_by_non_holder(self, mock_redis):
        """Should NOT release lock when called by a different holder."""
        mock_redis.eval = AsyncMock(return_value=0)  # Lua script fails
        lock = InventoryLock(mock_redis, ttl=300)
        
        result = await lock.release("LAPTOP-DELL-5540", "wrong-token")
        assert result is False
    
    async def test_is_locked(self, mock_redis):
        """Should correctly report lock status."""
        mock_redis.exists = AsyncMock(return_value=1)
        lock = InventoryLock(mock_redis, ttl=300)
        
        result = await lock.is_locked("LAPTOP-DELL-5540")
        assert result is True

    async def test_concurrent_reserve_stock(self, mock_redis, mock_db_session):
        """Issue 8: Test actual reserve_stock function concurrently.
        
        Simulates two concurrent requests trying to reserve 1 unit of a SKU
        that only has 1 unit available.
        """
        sku = "LAPTOP-DELL-5540"
        
        # Shared DB state
        inventory_item = Inventory(
            id=str(uuid.uuid4()),
            sku=sku,
            name="Dell Latitude",
            total_quantity=5,
            available_quantity=1,   # ONLY 1 AVAILABLE
            reserved_quantity=4,
            unit_cost=Decimal("1500.00")
        )
        
        # 1. Mock DB select to always return the shared item
        class MockResult:
            def scalar_one_or_none(self):
                return inventory_item
                
        async def mock_execute(stmt):
            return MockResult()
            
        mock_db_session.execute = AsyncMock(side_effect=mock_execute)
        
        # 2. Mock Redis SET NX to simulate a real mutex
        lock_holder = None
        
        async def mock_set(key, value, nx=False, ex=None):
            nonlocal lock_holder
            if nx:
                if lock_holder is None:
                    lock_holder = value
                    return True
                return None
            return True
            
        async def mock_eval(script, numkeys, key, value):
            nonlocal lock_holder
            if lock_holder == value:
                lock_holder = None
                return 1
            return 0
            
        mock_redis.set = mock_set
        mock_redis.eval = mock_eval

        # To force them to actually interleave, we patch uuid to return predictable tokens
        # but the lock guarantees mutual exclusion anyway.
        
        # 3. Fire both reserve_stock calls concurrently
        results = await asyncio.gather(
            reserve_stock(mock_db_session, mock_redis, sku, "request-A", quantity=1),
            reserve_stock(mock_db_session, mock_redis, sku, "request-B", quantity=1),
        )
        
        # 4. Assertions
        # Exactly one succeeded, one failed
        assert sum(1 for r in results if r is True) == 1
        assert sum(1 for r in results if r is False) == 1
        
        # Database state should reflect exactly 1 reservation
        assert inventory_item.available_quantity == 0  # 1 - 1
        assert inventory_item.reserved_quantity == 5   # 4 + 1
        
        # DB commit should be called exactly once
        assert mock_db_session.commit.call_count == 1
        
        # Lock should be completely released at the end
        assert lock_holder is None
