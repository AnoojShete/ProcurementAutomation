"""GSTIN (Goods and Services Tax Identification Number) verification.

TWO distinct offline checks before any live API call is made:
  1. Format check: 15-char structure (2-digit state code + 10-char PAN +
     1-char entity type + 'Z' + 1 check digit).
  2. Check-digit validation: modulo-36 Luhn-like algorithm over a defined
     character set — a format-passing GSTIN can still be invalid if this
     fails.

Only after BOTH pass is the live registry API attempted (gated by the
live_mode quota package from Prompt 0):
  - Result True  → call gstincheck.co.in, cache permanently, status='verified'
  - Result False → skip live call, status='structural_only'

On API outage (not same as the GSTIN itself being invalid):
  - status='pending', retried later — never silently bypass verification.

GSTIN is the primary dedup key for vendors when available: two vendor
names that differ but share a GSTIN are the same legal entity.
"""
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Modulo-36 character set used in the GSTIN check-digit algorithm.
# Characters ordered as per the GST specification (0-9 then A-Z).
_CHECKDIGIT_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# GSTIN regex: state(2) + PAN(10) + entity(1) + 'Z' + check(1) = 15 chars
# PAN: first 5 letters, next 4 digits, last 1 letter
_GSTIN_PATTERN = re.compile(
    r"^[0-3][0-9]"          # state code 01–37
    r"[A-Z]{5}"             # PAN: 5 alpha
    r"[0-9]{4}"             # PAN: 4 digits
    r"[A-Z]"                # PAN: 1 alpha
    r"[1-9A-Z]"             # entity code (non-zero)
    r"Z"                    # always 'Z' per spec
    r"[0-9A-Z]$"            # check digit
)

# Valid Indian state codes 01–37 (union territories share the same range).
_VALID_STATE_CODES = {f"{i:02d}" for i in range(1, 38)}

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

class GSTINStatus(str, Enum):
    VERIFIED = "verified"            # live registry confirmed active
    STRUCTURAL_ONLY = "structural_only"  # offline checks passed, live skipped
    PENDING = "pending"              # offline passed, live API unavailable
    INVALID = "invalid"              # failed format or check-digit
    CANCELLED = "cancelled"          # live registry: Cancelled/Suspended


@dataclass
class GSTINResult:
    gstin: str
    status: GSTINStatus
    data_source: str  # 'real' | 'simulated' | 'offline'
    legal_name: Optional[str] = None
    registration_status: Optional[str] = None  # Active | Cancelled | Suspended
    registration_date: Optional[str] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Offline validation
# ---------------------------------------------------------------------------

def validate_gstin_format(gstin: str) -> bool:
    """Check 1: 15-character structure and valid state code.
    Accepts both uppercase and lowercase (normalises internally).
    A format-passing GSTIN can still fail the check-digit — callers must
    run both checks before accepting a GSTIN as structurally valid."""
    if not isinstance(gstin, str) or len(gstin) != 15:
        return False
    upper = gstin.upper()
    if not _GSTIN_PATTERN.match(upper):
        return False
    state_code = upper[:2]
    return state_code in _VALID_STATE_CODES


def validate_gstin_checkdigit(gstin: str) -> bool:
    """Check 2: modulo-36 check-digit over the first 14 characters.

    Algorithm (per GSTN specification):
      total = 0
      factor = 1
      for each char c in gstin[0:14] (left to right):
          code_point = position of c in _CHECKDIGIT_CHARS (0..35)
          product = factor * code_point
          total += (product // 36) + (product % 36)  <-- digit-sum of product in base-36
          factor = 2 if factor == 1 else 1
      check_index = (36 - (total % 36)) % 36
      expected char = _CHECKDIGIT_CHARS[check_index]
    """
    if not isinstance(gstin, str):
        return False
    upper = gstin.upper()
    if len(upper) != 15:
        return False
    total = 0
    factor = 1
    for char in upper[:14]:
        if char not in _CHECKDIGIT_CHARS:
            return False
        code_point = _CHECKDIGIT_CHARS.index(char)
        product = factor * code_point
        total += (product // 36) + (product % 36)
        factor = 2 if factor == 1 else 1

    check_index = (36 - (total % 36)) % 36
    expected = _CHECKDIGIT_CHARS[check_index]
    return upper[14] == expected


def validate_gstin_offline(gstin: str) -> tuple[bool, str]:
    """Run BOTH offline checks. Returns (is_valid, reason_if_invalid)."""
    if not gstin:
        return False, "empty GSTIN"
    upper = gstin.upper().strip()
    if not validate_gstin_format(upper):
        return False, f"GSTIN '{upper}' failed format check (expected 15-char structure with valid state code)"
    if not validate_gstin_checkdigit(upper):
        return False, f"GSTIN '{upper}' failed check-digit validation"
    return True, ""


# ---------------------------------------------------------------------------
# Live registry lookup
# ---------------------------------------------------------------------------

_GSTIN_API_BASE = "https://sheet.gstincheck.co.in/check"

async def _fetch_gstin_live(gstin: str, api_key: str) -> dict:
    """Call the live GSTIN registry API. Raises httpx exceptions on failure."""
    url = f"{_GSTIN_API_BASE}/{api_key}/{gstin.upper()}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

async def verify_gstin(gstin: str, db=None) -> GSTINResult:
    """Main entry point for GSTIN verification.

    Flow:
      1. Offline format + check-digit.  Fail fast → INVALID.
      2. Check DB cache (permanent once verified).
      3. Check live_mode quota gate.
      4. Live API call (if gate passes) → VERIFIED or CANCELLED.
      5. Gate off / quota exhausted → STRUCTURAL_ONLY.
      6. API outage → PENDING (retry later).
    """
    upper = gstin.upper().strip() if gstin else ""

    # Step 1 — offline validation (both checks required)
    is_valid, reason = validate_gstin_offline(upper)
    if not is_valid:
        return GSTINResult(
            gstin=upper, status=GSTINStatus.INVALID,
            data_source="offline", error=reason,
        )

    # Step 2 — check persistent DB cache
    if db is not None:
        cached = await _get_cached_result(db, upper)
        if cached is not None:
            return cached

    # Step 3 — live_mode quota gate
    try:
        from shared.live_mode.checker import is_live_mode_enabled, check_and_reserve_quota
        live_ok = is_live_mode_enabled() and check_and_reserve_quota("gstin_live")
    except Exception as e:
        logger.warning(f"live_mode check failed ({e}); treating as disabled")
        live_ok = False

    if not live_ok:
        logger.info(f"GSTIN {upper}: live mode off or quota protected → structural_only")
        result = GSTINResult(
            gstin=upper, status=GSTINStatus.STRUCTURAL_ONLY,
            data_source="simulated",
        )
        if db is not None:
            await _upsert_cached_result(db, upper, result, raw_response=None)
        return result

    # Step 4 — live API call
    api_key = getattr(settings, "gstincheck_api_key", "")
    if not api_key:
        logger.warning("GSTINCHECK_API_KEY not set; falling back to structural_only")
        return GSTINResult(gstin=upper, status=GSTINStatus.STRUCTURAL_ONLY, data_source="simulated")

    try:
        data = await _fetch_gstin_live(upper, api_key)
        reg_status = (data.get("message", {}) or {}).get("sts", "") if isinstance(data.get("message"), dict) else ""
        legal_name = (data.get("message", {}) or {}).get("lgnm", "") if isinstance(data.get("message"), dict) else ""
        reg_date = (data.get("message", {}) or {}).get("rgdt", "") if isinstance(data.get("message"), dict) else ""

        if reg_status.lower() in ("cancelled", "suspended"):
            gstin_status = GSTINStatus.CANCELLED
        else:
            gstin_status = GSTINStatus.VERIFIED

        result = GSTINResult(
            gstin=upper, status=gstin_status, data_source="real",
            legal_name=legal_name or None,
            registration_status=reg_status or None,
            registration_date=reg_date or None,
        )
        if db is not None:
            await _upsert_cached_result(db, upper, result, raw_response=data)
        return result

    except httpx.HTTPStatusError as e:
        logger.error(f"GSTIN live API HTTP error for {upper}: {e}")
        # API error ≠ GSTIN invalid — don't reject the vendor
        return GSTINResult(gstin=upper, status=GSTINStatus.PENDING, data_source="offline",
                           error=f"live API returned {e.response.status_code}")

    except (httpx.RequestError, Exception) as e:
        logger.error(f"GSTIN live API unreachable for {upper}: {e}")
        return GSTINResult(gstin=upper, status=GSTINStatus.PENDING, data_source="offline",
                           error=f"live API unreachable: {e}")


# ---------------------------------------------------------------------------
# DB cache helpers (avoid re-burning quota on repeat lookups)
# ---------------------------------------------------------------------------

async def _get_cached_result(db, gstin: str) -> Optional[GSTINResult]:
    """Return a cached GSTINResult if one exists, else None."""
    from sqlalchemy import text
    try:
        row = await db.execute(
            text("SELECT gstin_verification_status, gstin_data_source, gstin_cached_response "
                 "FROM vendors WHERE gstin = :g LIMIT 1"),
            {"g": gstin},
        )
        r = row.fetchone()
        if r and r[0] and r[0] not in ("pending", "unverified"):
            resp = r[2] or {}
            return GSTINResult(
                gstin=gstin,
                status=GSTINStatus(r[0]),
                data_source=r[1] or "offline",
                legal_name=(resp.get("message") or {}).get("lgnm") if isinstance(resp.get("message"), dict) else None,
                registration_status=(resp.get("message") or {}).get("sts") if isinstance(resp.get("message"), dict) else None,
            )
    except Exception as e:
        logger.debug(f"GSTIN cache lookup failed (non-fatal): {e}")
    return None


async def _upsert_cached_result(db, gstin: str, result: GSTINResult, raw_response) -> None:
    """Write GSTIN verification result back to the vendor row that holds this GSTIN."""
    from sqlalchemy import text
    import json
    try:
        await db.execute(
            text(
                "UPDATE vendors SET gstin_verification_status=:status, gstin_data_source=:src, "
                "gstin_cached_response=:resp, gstin_cached_at=:at WHERE gstin=:g"
            ),
            {
                "status": result.status.value,
                "src": result.data_source,
                "resp": json.dumps(raw_response) if raw_response else None,
                "at": datetime.now(timezone.utc).isoformat(),
                "g": gstin,
            },
        )
        await db.flush()
    except Exception as e:
        logger.debug(f"GSTIN cache write failed (non-fatal): {e}")
