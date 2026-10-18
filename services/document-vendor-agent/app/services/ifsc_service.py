"""IFSC bank-code validation via the Razorpay IFSC API.

  GET https://ifsc.razorpay.com/{CODE}   (free, no API key, no rate-limit)

Three distinct outcomes — callers MUST treat them differently:
  valid   — 200 response; the IFSC exists and the bank/branch info is returned.
  invalid — 404 response; this specific IFSC code does not exist in the
            registry. Reject the payment-detail change.
  pending — 5xx or timeout; the *API* is unavailable, not the IFSC.
            Do NOT treat this the same as invalid. Set status='pending'
            and retry later — a third-party outage must never silently
            either block a legitimate payment detail or bypass the check.

Uppercase-normalization is applied before every lookup because IFSC codes
are case-sensitive at the API level; a lowercase submission 404s as
"invalid" even when the code is actually valid.
"""
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_RAZORPAY_IFSC_BASE = "https://ifsc.razorpay.com"


class IFSCStatus(str, Enum):
    VALID = "valid"
    INVALID = "invalid"    # 404 — IFSC genuinely does not exist
    PENDING = "pending"    # API unavailable — retry later


@dataclass
class IFSCResult:
    code: str
    status: IFSCStatus
    bank: Optional[str] = None
    branch: Optional[str] = None
    address: Optional[str] = None
    error: Optional[str] = None


async def validate_ifsc(code: str) -> IFSCResult:
    """Look up an IFSC code against the Razorpay registry.

    Always uppercase-normalizes before the request — a lowercase IFSC will
    404 as "not found" even when it's actually valid.

    Returns IFSCResult with status:
      VALID   → safe to accept the payment detail
      INVALID → reject with a clear error (404 from registry)
      PENDING → API unavailable; set ifsc_verification_status='pending'
                and schedule a retry
    """
    if not code:
        return IFSCResult(code="", status=IFSCStatus.INVALID, error="empty IFSC code")

    normalized = code.upper().strip()
    url = f"{_RAZORPAY_IFSC_BASE}/{normalized}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)

        if resp.status_code == 200:
            data = resp.json()
            return IFSCResult(
                code=normalized,
                status=IFSCStatus.VALID,
                bank=data.get("BANK"),
                branch=data.get("BRANCH"),
                address=data.get("ADDRESS"),
            )

        if resp.status_code == 404:
            logger.info(f"IFSC {normalized}: not found in Razorpay registry (404)")
            return IFSCResult(
                code=normalized, status=IFSCStatus.INVALID,
                error=f"IFSC code {normalized} does not exist in the registry",
            )

        # Any non-200/non-404 from the API → treat as availability issue
        logger.warning(f"IFSC lookup for {normalized} got unexpected status {resp.status_code}")
        return IFSCResult(
            code=normalized, status=IFSCStatus.PENDING,
            error=f"IFSC API returned unexpected status {resp.status_code}",
        )

    except (httpx.TimeoutException, httpx.ConnectError) as e:
        logger.warning(f"IFSC lookup timeout/connection error for {normalized}: {e}")
        return IFSCResult(
            code=normalized, status=IFSCStatus.PENDING,
            error=f"IFSC API unreachable: {e}",
        )

    except httpx.HTTPStatusError as e:
        status_code = e.response.status_code
        if status_code == 404:
            return IFSCResult(
                code=normalized, status=IFSCStatus.INVALID,
                error=f"IFSC code {normalized} does not exist (404)",
            )
        logger.warning(f"IFSC API HTTP error {status_code} for {normalized}: {e}")
        return IFSCResult(
            code=normalized, status=IFSCStatus.PENDING,
            error=f"IFSC API HTTP error {status_code}",
        )

    except Exception as e:
        logger.error(f"Unexpected error during IFSC lookup for {normalized}: {e}", exc_info=True)
        return IFSCResult(
            code=normalized, status=IFSCStatus.PENDING,
            error=f"Unexpected error: {e}",
        )
