import pytest
import asyncio
import sys
import os
from unittest.mock import AsyncMock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services.redis_lock import InventoryLock

@pytest.mark.asyncio
class TestRedisLock:
    """Test distributed locking for inventory reservation.
    
    The lock prevents two concurrent purchase requests from
    double-reserving the same inventory stock.
    """
    
    async def test_acquire_lock_success(self, mock_redis):
        """Should successfully acquire lock on unreserved resource."""
        mock_redis.set = AsyncMock(return_value=True)  # NX succeeds
        lock = InventoryLock(mock_redis, ttl=300)
        
        result = await lock.acquire("LAPTOP-DELL-5540", "request-001")
        assert result is True
        mock_redis.set.assert_called_once_with(
            "inventory:lock:LAPTOP-DELL-5540", "request-001", nx=True, ex=300
        )
    
    async def test_acquire_lock_already_held(self, mock_redis):
        """Should fail to acquire lock if already held by another request."""
        mock_redis.set = AsyncMock(return_value=None)  # NX fails
        lock = InventoryLock(mock_redis, ttl=300)
        
        result = await lock.acquire("LAPTOP-DELL-5540", "request-002")
        assert result is False
    
    async def test_release_lock_by_holder(self, mock_redis):
        """Should release lock when called by the holder."""
        mock_redis.eval = AsyncMock(return_value=1)  # Lua script succeeds
        lock = InventoryLock(mock_redis, ttl=300)
        
        result = await lock.release("LAPTOP-DELL-5540", "request-001")
        assert result is True
    
    async def test_release_lock_by_non_holder(self, mock_redis):
        """Should NOT release lock when called by a different holder."""
        mock_redis.eval = AsyncMock(return_value=0)  # Lua script fails
        lock = InventoryLock(mock_redis, ttl=300)
        
        result = await lock.release("LAPTOP-DELL-5540", "request-002")
        assert result is False
    
    async def test_race_condition_two_concurrent_requests(self, mock_redis):
        """Simulate two concurrent requests trying to reserve the same item.
        
        Only one should succeed - this is the core test for the locking mechanism.
        """
        call_count = 0
        
        async def mock_set(key, value, nx=False, ex=None):
            nonlocal call_count
            call_count += 1
            # First caller wins, second fails
            if call_count == 1:
                return True
            return None
        
        mock_redis.set = mock_set
        lock = InventoryLock(mock_redis, ttl=300)
        
        # Two concurrent acquire attempts
        results = await asyncio.gather(
            lock.acquire("LAPTOP-DELL-5540", "request-A"),
            lock.acquire("LAPTOP-DELL-5540", "request-B"),
        )
        
        # Exactly one should succeed
        assert sum(1 for r in results if r is True) == 1
        assert sum(1 for r in results if r is False) == 1
    
    async def test_is_locked(self, mock_redis):
        """Should correctly report lock status."""
        mock_redis.exists = AsyncMock(return_value=1)
        lock = InventoryLock(mock_redis, ttl=300)
        
        result = await lock.is_locked("LAPTOP-DELL-5540")
        assert result is True
