import redis.asyncio as redis
from redis.exceptions import LockError

class InventoryLock:
    def __init__(self, redis_client: redis.Redis, ttl: int = 300):
        self.redis = redis_client
        self.ttl = ttl
    
    async def acquire(self, resource_key: str, holder_id: str) -> bool:
        """Acquire a lock on a resource. Returns True if acquired."""
        lock_key = f"inventory:lock:{resource_key}"
        acquired = await self.redis.set(lock_key, holder_id, nx=True, ex=self.ttl)
        return acquired is not None
    
    async def release(self, resource_key: str, holder_id: str) -> bool:
        """Release lock only if held by this holder (safe release via Lua script)."""
        lock_key = f"inventory:lock:{resource_key}"
        lua_script = """
        if redis.call('get', KEYS[1]) == ARGV[1] then
            return redis.call('del', KEYS[1])
        else
            return 0
        end
        """
        result = await self.redis.eval(lua_script, 1, lock_key, holder_id)
        return result == 1
    
    async def is_locked(self, resource_key: str) -> bool:
        """Check if a resource is currently locked."""
        lock_key = f"inventory:lock:{resource_key}"
        return await self.redis.exists(lock_key) > 0
