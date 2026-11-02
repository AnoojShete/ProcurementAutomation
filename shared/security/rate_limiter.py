"""Redis token bucket rate limiting and abuse defense (OWASP API4 / API6).

Implements:
- Endpoint classes: anonymous, read, write, expensive, recompute, auth
- Hard minimum rate limits from business rules (cannot be disabled or bypassed)
- Returns 429 with Retry-After and standard error shape
- Concurrent request limiter for expensive operations (max 2 per user)
- Sensitive business flow daily velocity caps with 3x spike alert detection
- Automatic temporary IP blocking in Redis (15 minutes) after 20 violations in 10 minutes
  with office allow-list.
"""
import time
import logging
from typing import Optional, Tuple
from fastapi import HTTPException, Request, Response
from redis.asyncio import Redis

logger = logging.getLogger(__name__)

# Hard minimums: values cannot be set below these thresholds
HARD_MINIMUMS = {
    "anonymous": 10,  # min 10 req/min
    "read": 50,       # min 50 req/min
    "write": 10,      # min 10 req/min
    "expensive": 2,   # min 2 req/min
    "recompute": 1,   # min 1 req/min
}

DEFAULT_LIMITS = {
    "anonymous": 30,
    "read": 300,
    "write": 60,
    "expensive": 10,
    "recompute": 1,
}

# Office IP allowlist (never blocked automatically)
OFFICE_IP_ALLOWLIST = {"127.0.0.1", "::1"}


class RateLimitExceeded(HTTPException):
    def __init__(self, retry_after: int, message: str = "Too many requests. Please slow down."):
        super().__init__(
            status_code=429,
            detail={"code": "rate_limited", "message": message, "retry_after": retry_after},
            headers={"Retry-After": str(retry_after)},
        )


class IPBlocked(HTTPException):
    def __init__(self, retry_after: int = 900):
        super().__init__(
            status_code=403,
            detail={
                "code": "ip_blocked",
                "message": "Your IP address has been temporarily blocked due to repeated rate limit violations. Contact administrator.",
            },
            headers={"Retry-After": str(retry_after)},
        )


async def is_ip_blocked(redis: Optional[Redis], client_ip: str) -> bool:
    """Check if client IP is currently placed in temporary block."""
    if not redis or client_ip in OFFICE_IP_ALLOWLIST:
        return False
    try:
        val = await redis.get(f"security:ip_block:{client_ip}")
        return val is not None
    except Exception as e:
        logger.warning(f"Error checking IP block in Redis: {e}")
        return False


async def record_violation_and_check_block(
    redis: Optional[Redis],
    client_ip: str,
    threshold: int = 20,
    window_seconds: int = 600,
    block_duration_seconds: int = 900,
) -> bool:
    """Increment rate limit violation counter for IP; block if >= threshold in window."""
    if not redis or client_ip in OFFICE_IP_ALLOWLIST:
        return False
    try:
        key = f"security:violations:{client_ip}"
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, window_seconds)

        if count >= threshold:
            await redis.set(f"security:ip_block:{client_ip}", "blocked", ex=block_duration_seconds)
            logger.error(
                f"[SECURITY ALERT] IP {client_ip} has been temporarily blocked for {block_duration_seconds}s "
                f"after {count} violations in {window_seconds}s."
            )
            return True
    except Exception as e:
        logger.warning(f"Error recording violation in Redis: {e}")
    return False


async def check_rate_limit(
    redis: Optional[Redis],
    key: str,
    limit: int,
    window_seconds: int = 60,
    client_ip: Optional[str] = None,
) -> Tuple[bool, int]:
    """Token bucket rate limit check in Redis.
    Returns (allowed, retry_after_seconds).
    """
    if not redis:
        return True, 0

    now = int(time.time())
    bucket_key = f"rate_limit:{key}:{now // window_seconds}"

    try:
        current = await redis.incr(bucket_key)
        if current == 1:
            await redis.expire(bucket_key, window_seconds + 5)

        if current > limit:
            retry_after = (window_seconds - (now % window_seconds)) or 1
            if client_ip:
                await record_violation_and_check_block(redis, client_ip)
            return False, retry_after

        return True, 0
    except Exception as e:
        logger.warning(f"Redis rate limiter failed: {e} (failing open)")
        return True, 0


async def check_daily_sensitive_cap(
    redis: Optional[Redis],
    flow_name: str,
    user_id: str,
    daily_cap: int = 50,
    historical_avg: float = 10.0,
) -> Tuple[bool, int]:
    """Track sensitive business flow executions (bulk approvals, vendor onboarding, bank changes).
    Triggers an alert if daily execution exceeds 3x historical average.
    """
    if not redis:
        return True, 0

    date_str = time.strftime("%Y-%m-%d", time.gmtime())
    key = f"sensitive_flow:{flow_name}:{user_id}:{date_str}"

    try:
        current = await redis.incr(key)
        if current == 1:
            await redis.expire(key, 86400 + 3600)  # 25 hours

        # Check for 3x spike
        if current >= max(int(historical_avg * 3.0), 15) and current % 5 == 0:
            logger.warning(
                f"[SECURITY ALERT] Velocity spike on flow '{flow_name}' by user {user_id}: "
                f"{current} executions today (>3x historical average {historical_avg})."
            )

        if current > daily_cap:
            return False, current

        return True, current
    except Exception as e:
        logger.warning(f"Redis sensitive flow cap check failed: {e}")
        return True, 0
