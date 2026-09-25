"""Shared Business Rules Engine client.
Provides in-memory caching with TTL (5 minutes) and on-demand invalidation via Kafka events.
Falls back safely to caller-provided defaults if auth-service is unreachable.
"""
import os
import time
import logging
from typing import Any, Optional, Dict
import httpx

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 300  # 5 minutes

_cache: Dict[str, Any] = {}
_cache_expiry: float = 0.0
_rule_expiries: Dict[str, float] = {}


def get_auth_service_url() -> str:
    return os.environ.get("AUTH_SERVICE_URL", "http://auth-service:8005").rstrip("/")


def get_internal_secret() -> str:
    return os.environ.get("RULES_ENGINE_INTERNAL_SECRET", "dev-rules-secret-change-me")


def fetch_all_rules() -> Dict[str, Any]:
    url = f"{get_auth_service_url()}/internal/business-rules"
    secret = get_internal_secret()
    headers = {"X-Internal-Service-Secret": secret}
    try:
        with httpx.Client(timeout=2.0) as client:
            resp = client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json().get("data", {})
                return data
            else:
                logger.warning(f"Rules engine failed to fetch rules: HTTP {resp.status_code}")
                return {}
    except Exception as e:
        logger.warning(f"Rules engine: auth-service unreachable ({e})")
        return {}


def get_rule(key: str, fallback: Any = None) -> Any:
    """Retrieve rule value by key.
    Uses in-memory cache with 5-minute TTL.
    If auth-service is unreachable or cache empty and fetch fails, returns fallback.
    """
    global _cache, _cache_expiry, _rule_expiries
    now = time.time()

    key_valid = key in _cache and now <= _rule_expiries.get(key, 0)

    if not key_valid and now > _cache_expiry:
        rules = fetch_all_rules()
        if rules:
            _cache.update(rules)
            _cache_expiry = now + CACHE_TTL_SECONDS
            for rk in rules.keys():
                _rule_expiries[rk] = now + CACHE_TTL_SECONDS
        else:
            # Backoff for 15s before attempting to query auth-service again
            _cache_expiry = now + 15.0

    if key in _cache:
        return _cache[key]

    return fallback


def invalidate_rule(key: str) -> None:
    """Invalidate a specific rule key in the local cache immediately."""
    global _cache, _rule_expiries
    _cache.pop(key, None)
    _rule_expiries.pop(key, None)


def update_rule_cache(key: str, value: Any) -> None:
    """Update a specific rule key in the local cache immediately."""
    global _cache, _rule_expiries
    _cache[key] = value
    _rule_expiries[key] = time.time() + CACHE_TTL_SECONDS


def clear_cache() -> None:
    """Clear entire cache."""
    global _cache, _cache_expiry, _rule_expiries
    _cache.clear()
    _rule_expiries.clear()
    _cache_expiry = 0.0
