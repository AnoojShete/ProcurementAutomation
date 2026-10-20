"""Redis-backed circuit breaker per external source with in-memory fallback (Prompt 9C Section E2).

Key pattern: risk:cb:{source_id}
State machine:
  CLOSED: requests go through.
  3 consecutive timeouts/5xx within a 5-minute sliding window -> OPEN.
  OPEN duration: 15 minutes. While OPEN, requests fast-fail immediately.
  After 15 minutes -> HALF-OPEN: exactly 1 probe request is allowed.
  If probe succeeds -> CLOSED (counter reset).
  If probe fails -> OPEN for another 15 minutes.
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

FAIL_THRESHOLD = 3
SLIDING_WINDOW_SEC = 300  # 5 minutes
OPEN_DURATION_SEC = 900   # 15 minutes

# In-memory fallback dictionary
_in_memory_state: Dict[str, Dict[str, Any]] = {}


def _get_memory_record(source_id: str) -> Dict[str, Any]:
    if source_id not in _in_memory_state:
        _in_memory_state[source_id] = {
            "state": "CLOSED",
            "failures": [],
            "open_until": 0.0,
            "half_open_in_flight": False,
        }
    return _in_memory_state[source_id]


class CircuitBreaker:
    def __init__(self, source_id: str, redis_client=None):
        self.source_id = source_id
        self.redis = redis_client
        self.key = f"risk:cb:{source_id}"

    async def _get_state(self) -> Dict[str, Any]:
        if self.redis is not None:
            try:
                data = await self.redis.get(self.key)
                if data:
                    return json.loads(data)
            except Exception as e:
                logger.warning("Redis error in circuit breaker read for %s: %s; falling back to memory", self.source_id, e)
        return _get_memory_record(self.source_id)

    async def _save_state(self, state: Dict[str, Any]) -> None:
        if self.redis is not None:
            try:
                # TTL can be set to 2x open duration to auto-clean idle entries
                await self.redis.set(self.key, json.dumps(state), ex=OPEN_DURATION_SEC * 2)
                return
            except Exception as e:
                logger.warning("Redis error in circuit breaker write for %s: %s; falling back to memory", self.source_id, e)
        _in_memory_state[self.source_id] = state

    async def can_execute(self) -> bool:
        """Returns True if the request is permitted to proceed, False if circuit is OPEN."""
        now = time.time()
        record = await self._get_state()
        state = record.get("state", "CLOSED")
        open_until = record.get("open_until", 0.0)

        if state == "CLOSED":
            return True

        if state == "OPEN":
            if now < open_until:
                return False
            # Transition to HALF-OPEN after open_until elapsed
            record["state"] = "HALF_OPEN"
            record["half_open_in_flight"] = True
            await self._save_state(record)
            return True

        if state == "HALF_OPEN":
            # If a probe is already in flight, block other requests
            if record.get("half_open_in_flight", False):
                return False
            record["half_open_in_flight"] = True
            await self._save_state(record)
            return True

        return True

    async def record_success(self) -> None:
        """Record successful execution (resets breaker to CLOSED)."""
        record = {
            "state": "CLOSED",
            "failures": [],
            "open_until": 0.0,
            "half_open_in_flight": False,
        }
        await self._save_state(record)

    async def record_failure(self) -> None:
        """Record a timeout or 5xx error."""
        now = time.time()
        record = await self._get_state()
        state = record.get("state", "CLOSED")

        if state == "HALF_OPEN":
            # Probe failed: back to OPEN for 15 minutes
            record["state"] = "OPEN"
            record["open_until"] = now + OPEN_DURATION_SEC
            record["half_open_in_flight"] = False
            await self._save_state(record)
            return

        # Prune failures older than sliding window
        failures: List[float] = [t for t in record.get("failures", []) if (now - t) <= SLIDING_WINDOW_SEC]
        failures.append(now)
        record["failures"] = failures

        if len(failures) >= FAIL_THRESHOLD:
            record["state"] = "OPEN"
            record["open_until"] = now + OPEN_DURATION_SEC
            record["half_open_in_flight"] = False

        await self._save_state(record)
