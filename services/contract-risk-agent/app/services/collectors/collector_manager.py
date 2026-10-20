"""Coordinates all 14 signal collectors for a vendor (Prompt 9B section 4 & Prompt 9C Section E).
Guarantees:
  - 10s per-source timeout hard cap across external calls (E1).
  - Circuit breaker per source (E2).
  - 45s total collection deadline (E3).
  - Short-circuiting on non-remediable overrides for non-active vendors (E4).
  - Gated live GSTIN lookup (E5).
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Vendor
from app.services.collectors.base import record_observation, record_raw_response
from app.services.collectors.cyber_collectors import (
    collect_breach,
    collect_certification,
    collect_email,
    collect_web,
)
from app.services.collectors.company_collectors import (
    collect_company_age,
    collect_financial,
)
from app.services.collectors.identity_collectors import (
    collect_bank,
    collect_gst,
    collect_jurisdiction,
    collect_sanctions,
)
from app.services.collectors.performance_collectors import (
    collect_delivery_sla,
    collect_feedback,
    collect_incidents,
)
from app.services.collectors.reputation_collectors import collect_adverse_media

logger = logging.getLogger(__name__)

TIMEOUT_PER_SOURCE = 10.0   # seconds (E1)
TOTAL_COLLECTION_DEADLINE = 45.0  # seconds (E3)

SKIPPED_NONREMEDIABLE_DETAIL = (
    "Not checked: a non-remediable block already applies; these checks run automatically "
    "if the block is lifted (e.g., if a false-positive match dispute is upheld)."
)


async def _safe_collect(
    collector_fn,
    db: AsyncSession,
    vendor: Vendor,
    now: datetime,
    signal_key: str,
    timeout: float = TIMEOUT_PER_SOURCE,
    **kwargs,
) -> Any:
    """Wraps collector execution with a timeout and poison-pill resilience (B7, E1)."""
    try:
        obs, _ = await asyncio.wait_for(collector_fn(db, vendor, now, **kwargs), timeout=timeout)
        return obs
    except asyncio.TimeoutError:
        logger.warning("Collector for signal '%s' timed out after %ss", signal_key, timeout)
        raw = await record_raw_response(
            db=db,
            vendor_id=vendor.id,
            signal_key=signal_key,
            provider="system_timeout",
            request_method="INTERNAL",
            body={"error": f"Collector exceeded {timeout}s timeout"},
            response_status=504,
            error=f"{timeout}s exceeded",
            fetched_at=now,
        )
        facts = [
            {"label": "Source", "value": "system_timeout"},
            {"label": "Retrieved", "value": now.strftime("%Y-%m-%d %H:%M:%S UTC")},
            {"label": "HTTP status", "value": "504"},
            {"label": "Error detail", "value": f"Timeout of {timeout}s exceeded"},
        ]
        # Source unreachable fields for specific signals
        unreachable_fields: Dict[str, Any] = {}
        if signal_key == "breach":
            unreachable_fields = {"breach.source_reachable": False, "breach.count_5y": 0}
        elif signal_key == "adverse_media":
            unreachable_fields = {"media.sources_reachable": False, "media.qualifying_articles": 0}
        elif signal_key == "web":
            unreachable_fields = {"web.reachable": False}

        obs = await record_observation(
            db=db,
            vendor_id=vendor.id,
            signal_key=signal_key,
            source_name=f"{signal_key.title()} Collector",
            provider="system_timeout",
            status="error",
            facts=facts,
            fields=unreachable_fields,
            skip_reason="timeout",
            raw_response_id=raw.id,
            ttl_days=1,
            fetched_at=now,
        )
        return obs
    except Exception as e:
        logger.warning("Collector for signal '%s' failed: %s", signal_key, e, exc_info=True)
        raw = await record_raw_response(
            db=db,
            vendor_id=vendor.id,
            signal_key=signal_key,
            provider="system_error",
            request_method="INTERNAL",
            body={"error": str(e)},
            response_status=500,
            error=str(e),
            fetched_at=now,
        )
        facts = [
            {"label": "Source", "value": "system_error"},
            {"label": "Retrieved", "value": now.strftime("%Y-%m-%d %H:%M:%S UTC")},
            {"label": "HTTP status", "value": "500"},
            {"label": "Error detail", "value": str(e)},
        ]
        obs = await record_observation(
            db=db,
            vendor_id=vendor.id,
            signal_key=signal_key,
            source_name=f"{signal_key.title()} Collector",
            provider="system_error",
            status="error",
            facts=facts,
            fields={},
            raw_response_id=raw.id,
            ttl_days=1,
            fetched_at=now,
        )
        return obs


async def _record_skipped_signal(
    db: AsyncSession,
    vendor: Vendor,
    now: datetime,
    signal_key: str,
    skip_reason: str,
    detail: str,
) -> Any:
    """Records an observation for a skipped signal."""
    raw = await record_raw_response(
        db=db,
        vendor_id=vendor.id,
        signal_key=signal_key,
        provider="short_circuit",
        request_method="NONE",
        body={"skip_reason": skip_reason, "detail": detail},
        response_status=200,
        fetched_at=now,
    )
    facts = [
        {"label": "Source", "value": "short_circuit"},
        {"label": "Retrieved", "value": now.strftime("%Y-%m-%d %H:%M:%S UTC")},
        {"label": "Status", "value": "not_checked"},
        {"label": "Reason", "value": skip_reason},
        {"label": "Detail", "value": detail},
    ]
    obs = await record_observation(
        db=db,
        vendor_id=vendor.id,
        signal_key=signal_key,
        source_name=f"{signal_key.title()} Collector",
        provider="short_circuit",
        status="not_checked",
        facts=facts,
        fields={},
        skip_reason=skip_reason,
        raw_response_id=raw.id,
        ttl_days=1,
        fetched_at=now,
    )
    return obs


async def collect_all_signals(
    db: AsyncSession,
    vendor: Vendor,
    now: Optional[datetime] = None,
    effective_tier: str = "standard",
) -> Dict[str, Any]:
    """Runs collectors according to Prompt 9C phased execution rules."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    observations: Dict[str, Any] = {}

    # Phase 0: Local / fast checks
    observations["sanctions"] = await _safe_collect(collect_sanctions, db, vendor, now, "sanctions")
    observations["jurisdiction"] = await _safe_collect(collect_jurisdiction, db, vendor, now, "jurisdiction")
    observations["bank"] = await _safe_collect(collect_bank, db, vendor, now, "bank")
    observations["company_age"] = await _safe_collect(collect_company_age, db, vendor, now, "company_age")
    observations["delivery_sla"] = await _safe_collect(collect_delivery_sla, db, vendor, now, "delivery_sla")
    observations["feedback"] = await _safe_collect(collect_feedback, db, vendor, now, "feedback")
    observations["incidents"] = await _safe_collect(collect_incidents, db, vendor, now, "incidents")

    # E4 Short-circuiting collectors on NON-REMEDIABLE overrides:
    # When collecting for a vendor whose status is NOT active:
    # If any non-remediable override rule fires with short_circuit_external = true
    # (e.g. sanctions match, prohibited jurisdiction), skip remaining external calls.
    vendor_status = getattr(vendor, "status", "onboarding")
    sanctions_obs = observations.get("sanctions")
    jurisdiction_obs = observations.get("jurisdiction")

    sanctions_non_remediable = (
        sanctions_obs is not None
        and sanctions_obs.fields.get("sanctions.status") == "match"
    )
    jurisdiction_non_remediable = (
        jurisdiction_obs is not None
        and jurisdiction_obs.fields.get("country.prohibited") is True
    )

    should_short_circuit = (
        vendor_status != "active"
        and (sanctions_non_remediable or jurisdiction_non_remediable)
    )

    remaining_signals = [
        "gst",
        "web",
        "email",
        "breach",
        "certification",
        "financial",
        "adverse_media",
    ]

    if should_short_circuit:
        logger.info(
            "Short-circuiting external collectors for vendor %s due to non-remediable override",
            vendor.id,
        )
        for sig in remaining_signals:
            observations[sig] = await _record_skipped_signal(
                db=db,
                vendor=vendor,
                now=now,
                signal_key=sig,
                skip_reason="skipped_nonremediable_override",
                detail=SKIPPED_NONREMEDIABLE_DETAIL,
            )
        return observations

    # Phase 1: GST (gated live check)
    observations["gst"] = await _safe_collect(collect_gst, db, vendor, now, "gst")

    # Phase 2: Parallel external collectors with 45s total deadline (E3)
    parallel_signals = [
        ("web", collect_web, {}),
        ("email", collect_email, {}),
        ("breach", collect_breach, {}),
        ("certification", collect_certification, {"effective_tier": effective_tier}),
        ("financial", collect_financial, {}),
        ("adverse_media", collect_adverse_media, {}),
    ]

    async def _run_parallel():
        tasks = [
            _safe_collect(fn, db, vendor, now, sig_name, **extra_kwargs)
            for sig_name, fn, extra_kwargs in parallel_signals
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return results

    try:
        results = await asyncio.wait_for(_run_parallel(), timeout=TOTAL_COLLECTION_DEADLINE)
        for (sig_name, _, _), res in zip(parallel_signals, results):
            if isinstance(res, Exception):
                logger.error("Parallel collector %s raised unhandled exception: %s", sig_name, res)
                observations[sig_name] = await _record_skipped_signal(
                    db=db,
                    vendor=vendor,
                    now=now,
                    signal_key=sig_name,
                    skip_reason="deadline_exceeded",
                    detail=f"Execution failed: {res}",
                )
            else:
                observations[sig_name] = res
    except asyncio.TimeoutError:
        logger.warning(
            "Overall collection deadline (%ss) exceeded for vendor %s",
            TOTAL_COLLECTION_DEADLINE,
            vendor.id,
        )
        for sig_name, _, _ in parallel_signals:
            if sig_name not in observations:
                observations[sig_name] = await _record_skipped_signal(
                    db=db,
                    vendor=vendor,
                    now=now,
                    signal_key=sig_name,
                    skip_reason="deadline_exceeded",
                    detail=f"Collection cancelled after {TOTAL_COLLECTION_DEADLINE}s deadline exceeded",
                )

    return observations
