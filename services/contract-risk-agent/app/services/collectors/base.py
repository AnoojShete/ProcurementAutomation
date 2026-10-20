"""Base collector infrastructure for vendor risk signals (Prompt 9B section 2.2, 2.3, 4).
Handles secret redaction, SHA-256 calculation, MinIO compression for >256KB payloads,
retention expiration, and structured observation recording.
"""
import gzip
import hashlib
import json
import logging
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import VendorSignalObservation, VendorSignalRawResponse

logger = logging.getLogger(__name__)

SECRET_PATTERNS = [
    re.compile(r"(?i)(key|token|authorization|secret|password|set-cookie|cookie)"),
]
SENSITIVE_PARAM_NAMES = {"key", "token", "apikey", "api_key", "secret", "password", "auth"}


def redact_text(text: str) -> str:
    """Replaces potential API keys or tokens in strings with '***'."""
    if not text:
        return text
    # Mask bearer tokens
    text = re.sub(r"(?i)bearer\s+[a-zA-Z0-9_\-\.]+", "Bearer ***", text)
    # Mask query params named key/token/apikey
    text = re.sub(r"(?i)(key|token|apikey|secret)=[^&\s]+", r"\1=***", text)
    return text


def redact_dict(data: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Recursively replaces sensitive keys with '***'."""
    if data is None:
        return None
    redacted = {}
    for k, v in data.items():
        if any(p.search(str(k)) for p in SECRET_PATTERNS) or str(k).lower() in SENSITIVE_PARAM_NAMES:
            redacted[k] = "***"
        elif isinstance(v, dict):
            redacted[k] = redact_dict(v)
        elif isinstance(v, list):
            redacted[k] = [redact_dict(item) if isinstance(item, dict) else item for item in v]
        elif isinstance(v, str):
            redacted[k] = redact_text(v)
        else:
            redacted[k] = v
    return redacted


def compute_retention_date(fetched_at: datetime, retention_months: int = 24) -> date:
    """Computes retention date (default 24 months from fetched_at)."""
    # Approximate 24 months as 730 days
    return (fetched_at + timedelta(days=retention_months * 30.5)).date()


def days_since(d: Any, now: Any) -> int:
    """Computes whole days between d and now across month and leap-year boundaries."""
    if isinstance(d, datetime):
        d = d.date()
    if isinstance(now, datetime):
        now = now.date()
    return (now - d).days


def months_between(d1: Any, d2: Any) -> int:
    """Computes whole calendar months between d1 and d2 across year boundaries."""
    if isinstance(d1, datetime):
        d1 = d1.date()
    if isinstance(d2, datetime):
        d2 = d2.date()
    months = (d2.year - d1.year) * 12 + (d2.month - d1.month)
    if d2.day < d1.day:
        months -= 1
    return max(0, months)


def redact_secrets(
    url: str,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, Any]] = None,
) -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
    """Redacts secrets in url, params, and headers."""
    redacted_url = redact_text(url)
    redacted_params = redact_dict(params) or {}
    redacted_headers = redact_dict(headers) or {}
    return redacted_url, redacted_params, redacted_headers


async def record_raw_response(
    db: AsyncSession,
    vendor_id: str,
    signal_key: str,
    provider: str,
    request_method: str,
    body: Any,
    source_id: Optional[str] = None,
    request_url: Optional[str] = None,
    request_params: Optional[Dict[str, Any]] = None,
    response_status: Optional[int] = None,
    response_headers: Optional[Dict[str, Any]] = None,
    duration_ms: int = 0,
    error: Optional[str] = None,
    fetched_at: Optional[datetime] = None,
) -> VendorSignalRawResponse:
    """Persists raw response with secret redaction and SHA-256 computation."""
    fetched_at = fetched_at or datetime.now(timezone.utc)
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)

    # Redact request metadata
    redacted_url = redact_text(request_url) if request_url else None
    redacted_params = redact_dict(request_params)

    # Prepare body text or serialized JSON
    if isinstance(body, (dict, list)):
        # Redact secrets inside body before storage
        body_cleaned = redact_dict(body) if isinstance(body, dict) else [
            redact_dict(x) if isinstance(x, dict) else x for x in body
        ]
        body_str = json.dumps(body_cleaned, sort_keys=True, separators=(",", ":"))
    elif isinstance(body, str):
        body_str = redact_text(body)
    elif body is None:
        body_str = ""
    else:
        body_str = redact_text(str(body))

    body_bytes = body_str.encode("utf-8")
    body_sha256 = hashlib.sha256(body_bytes).hexdigest()
    byte_count = len(body_bytes)

    body_text_col = body_str
    body_object_key_col = None

    # Handle bodies > 256 KB (Prompt 9B section 2.2)
    if byte_count > 256 * 1024:
        # Compress and designate MinIO object key
        compressed = gzip.compress(body_bytes)
        obj_key = f"raw_responses/{vendor_id}/{signal_key}/{body_sha256}.json.gz"
        body_object_key_col = obj_key
        body_text_col = None  # Body stored in object storage

    from shared.rules_engine import get_rule
    retention_months = int(get_rule("risk.raw_retention_months", fallback=24))
    retention_date = compute_retention_date(fetched_at, retention_months)

    raw_row = VendorSignalRawResponse(
        id=str(uuid.uuid4()),
        vendor_id=vendor_id,
        signal_key=signal_key,
        source_id=source_id,
        provider=provider,
        request_method=request_method,
        request_url_redacted=redacted_url,
        request_params_redacted=redacted_params,
        response_status=response_status,
        response_headers_subset=redact_dict(response_headers),
        body_text=body_text_col,
        body_object_key=body_object_key_col,
        body_sha256=body_sha256,
        body_bytes=byte_count,
        fetched_at=fetched_at,
        duration_ms=duration_ms,
        error=error,
        retention_until=retention_date,
    )
    db.add(raw_row)
    await db.flush()
    return raw_row


async def record_observation(
    db: AsyncSession,
    vendor_id: str,
    signal_key: str,
    source_name: str,
    provider: str,
    status: str,  # ok, error, rate_limited, not_checked, not_applicable
    facts: List[Dict[str, str]],
    fields: Dict[str, Any],
    raw_response_id: Optional[str] = None,
    evidence_id: Optional[str] = None,
    record_refs: Optional[List[str]] = None,
    source_id: Optional[str] = None,
    ttl_days: int = 30,
    observed_at: Optional[datetime] = None,
    fetched_at: Optional[datetime] = None,
    created_by: str = "system",
    manual_correction: bool = False,
    correction_reason: Optional[str] = None,
    corrects_observation_id: Optional[str] = None,
    extraction: Optional[Dict[str, Any]] = None,
    skip_reason: Optional[str] = None,
) -> VendorSignalObservation:
    """Persists a parsed observation with facts strictly ordered."""
    now = datetime.now(timezone.utc)
    observed_at = observed_at or now
    fetched_at = fetched_at or now
    expires_at = fetched_at + timedelta(days=ttl_days)

    obs_row = VendorSignalObservation(
        id=str(uuid.uuid4()),
        vendor_id=vendor_id,
        signal_key=signal_key,
        source_id=source_id,
        source_name=source_name,
        provider=provider,
        status=status,
        facts=facts,
        fields=fields,
        observed_at=observed_at,
        fetched_at=fetched_at,
        expires_at=expires_at,
        raw_response_id=raw_response_id,
        evidence_id=evidence_id,
        record_refs=record_refs or [],
        created_by=created_by,
        manual_correction=manual_correction,
        correction_reason=correction_reason,
        corrects_observation_id=corrects_observation_id,
        extraction=extraction,
        skip_reason=skip_reason,
    )
    db.add(obs_row)
    await db.flush()
    return obs_row
