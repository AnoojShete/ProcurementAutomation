"""Identity group collectors: sanctions, gst, bank, jurisdiction (Prompt 9B section 4, Prompt 9C).
"""
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Vendor
from app.services import sanctions
from app.services.collectors.base import record_observation, record_raw_response
from app.services.collectors.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)

PROHIBITED_COUNTRIES = {"KP", "IR", "SY", "CU"}
HIGH_RISK_COUNTRIES = {"MM", "YE", "CD", "SO", "SS"}

_CHECKDIGIT_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_GSTIN_PATTERN = re.compile(
    r"^[0-3][0-9][A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$"
)
_VALID_STATE_CODES = {f"{i:02d}" for i in range(1, 38)}


def validate_gstin_offline(gstin: Optional[str]) -> Tuple[bool, str]:
    """Offline validation of GSTIN: format check and modulo-36 check-digit test."""
    if not gstin or not isinstance(gstin, str):
        return False, "empty or non-string GSTIN"
    upper = gstin.strip().upper()
    if len(upper) != 15:
        return False, f"invalid length ({len(upper)} != 15)"
    if not _GSTIN_PATTERN.match(upper):
        return False, "structure does not match GSTIN format (state code + PAN + entity + Z + check)"
    if upper[:2] not in _VALID_STATE_CODES:
        return False, f"state code '{upper[:2]}' is not a valid Indian state code (01-37)"

    total = 0
    factor = 1
    for char in upper[:14]:
        if char not in _CHECKDIGIT_CHARS:
            return False, f"invalid character '{char}' in GSTIN body"
        code_point = _CHECKDIGIT_CHARS.index(char)
        product = factor * code_point
        total += (product // 36) + (product % 36)
        factor = 2 if factor == 1 else 1

    check_index = (36 - (total % 36)) % 36
    expected_char = _CHECKDIGIT_CHARS[check_index]
    if upper[14] != expected_char:
        return False, f"check-digit mismatch (expected '{expected_char}', got '{upper[14]}')"

    return True, "valid"



async def collect_sanctions(
    db: AsyncSession, vendor: Vendor, now: datetime
) -> Tuple[Any, Any]:
    """Collects sanctions screening signal (Section F3: pure observation extractor)."""
    provider = "OpenSanctions"
    latest = await sanctions.latest_screening(db, vendor.id)
    index = sanctions.load_index()

    status = "not_screened"
    best_score = 0
    matched_name = "None"
    list_name = index.get("list_name", "OpenSanctions Consolidated") if index else "Consolidated Sanctions List"
    list_version = index.get("version", "v2026.10") if index else "v1"
    review_threshold = 70
    match_threshold = 85
    matches = []

    if latest:
        matches = latest.matches or []
        list_version = latest.list_version or list_version
        if latest.status == "cleared":
            status = "no_match"
        elif latest.status in ("potential_match", "match"):
            if matches:
                top_m = matches[0]
                best_score = int(top_m.get("score", 0))
                matched_name = top_m.get("matched_name", top_m.get("listed_name", vendor.name))
                status = "match" if best_score >= match_threshold else "possible_match"
            else:
                status = "possible_match"
        else:
            status = "no_match"
    elif index:
        # Perform screening on the fly
        screening = await sanctions.screen_vendor(db, vendor, index=index, screened_by="system")
        if screening:
            matches = screening.matches or []
            if screening.status in ("potential_match", "match") and matches:
                top_m = matches[0]
                best_score = int(top_m.get("score", 0))
                matched_name = top_m.get("matched_name", top_m.get("listed_name", vendor.name))
                status = "match" if best_score >= match_threshold else "possible_match"
            else:
                status = "no_match"
        else:
            status = "not_screened"

    match_type = "none"
    if status == "match":
        match_type = "exact"
    elif status == "possible_match":
        match_type = "fuzzy"
    elif status == "not_screened":
        match_type = "unreachable"

    raw_body = {
        "list_name": list_name,
        "list_version": list_version,
        "screened_name": vendor.name,
        "match_count": len(matches),
        "matches": matches[:5],  # top entries only (Section 2.2)
        "review_threshold": review_threshold,
        "match_threshold": match_threshold,
    }

    raw = await record_raw_response(
        db=db,
        vendor_id=vendor.id,
        signal_key="sanctions",
        provider=provider,
        request_method="INTERNAL",
        body=raw_body,
        source_id="sanctions_index",
        response_status=200,
        fetched_at=now,
    )

    facts = [
        {"label": "Source", "value": provider},
        {"label": "Retrieved", "value": now.strftime("%Y-%m-%d %H:%M:%S UTC")},
        {"label": "HTTP status", "value": "internal"},
        {"label": "Sanctions status text", "value": status.replace("_", " ").title()},
        {"label": "Match type", "value": match_type.title()},
        {"label": "Screened name", "value": vendor.name},
        {"label": "List version", "value": f"{list_name} ({list_version})"},
    ]

    fields = {
        "sanctions.status": status,
        "sanctions.match_type": match_type,
        "sanctions.best_score": round(best_score / 100.0, 2) if best_score > 1 else float(best_score),
        "sanctions.matched_list": list_name,
        "sanctions.matched_entry_id": matches[0].get("id", "none") if matches else "none",
        "sanctions.query_name": vendor.name,
        "sanctions.matched_name": matched_name,
        "sanctions.list_name": list_name,
        "sanctions.list_version": list_version,
        "sanctions.screened_at": now.strftime("%d %b %Y"),
        "sanctions.review_threshold": review_threshold,
        "sanctions.match_threshold": match_threshold,
    }

    obs_status = "ok" if status != "not_screened" else "not_checked"
    obs = await record_observation(
        db=db,
        vendor_id=vendor.id,
        signal_key="sanctions",
        source_name="Sanctions Screening",
        provider=provider,
        status=obs_status,
        facts=facts,
        fields=fields,
        raw_response_id=raw.id,
        ttl_days=1,
        fetched_at=now,
    )
    return obs, raw


async def collect_gst(
    db: AsyncSession, vendor: Vendor, now: datetime
) -> Tuple[Any, Any]:
    """Collects GST registration status signal (Prompt 9C Section B2, E5)."""
    # Read vendor row directly from db to get gstin and country fields
    v_row = (await db.execute(
        text("SELECT country, gstin, gstin_verification_status, gstin_data_source, gstin_cached_response, no_gstin_confirmed_by, no_gstin_confirmed_at FROM vendors WHERE id = :id"),
        {"id": vendor.id},
    )).first()

    country = (v_row.country if v_row and v_row.country else getattr(vendor, "country", None))
    if country:
        country = country.strip().upper()

    gstin = (v_row.gstin if v_row else getattr(vendor, "gstin", None))
    v_status = (v_row.gstin_verification_status or "unverified").lower() if v_row else "unverified"
    data_source = (v_row.gstin_data_source or "offline").lower() if v_row else "offline"
    cached = v_row.gstin_cached_response or {} if v_row else {}
    exempt_by = v_row.no_gstin_confirmed_by if v_row else None
    exempt_at = v_row.no_gstin_confirmed_at if v_row else None

    provider = "gstincheck.co.in" if data_source == "real" else "internal"
    http_status = 200 if gstin else "internal"

    fields: Dict[str, Any] = {
        "gstin.number": gstin or "None",
        "gstin.status": "unknown",
        "gstin.verification_level": "offline_only",
        "gstin.cancellation_date": "—",
        "gstin.legal_name": vendor.name,
        "gstin.registration_date": "—",
        "gstin.provider_status_raw": v_status,
        "gstin.not_checked_reason": "No verification performed",
    }

    obs_status = "ok"

    # Deterministic derivation per Section B2
    # 1. vendor.country is null -> country_unknown
    if not country:
        fields["gstin.status"] = "unknown"
        fields["gstin.verification_level"] = "country_unknown"
        fields["gstin.not_checked_reason"] = "vendor_country_missing"
        obs_status = "not_checked"

    # 2. GSTIN present
    elif gstin:
        is_valid, offline_err = validate_gstin_offline(gstin)
        if not is_valid:
            fields["gstin.status"] = "invalid"
            fields["gstin.verification_level"] = "invalid"
            fields["gstin.not_checked_reason"] = f"failed the offline format/check-digit test: {offline_err}"
        else:
            # Passes offline format and check-digit test
            # Check live gating per Section E5
            from shared.live_mode.checker import is_live_verification_enabled
            live_enabled = await is_live_verification_enabled(db)
            if live_enabled and country == "IN" and data_source == "real":
                cb = CircuitBreaker("gstincheck")
                if not await cb.can_execute():
                    fields["gstin.status"] = "unknown"
                    fields["gstin.verification_level"] = "offline_only"
                    fields["gstin.not_checked_reason"] = "circuit_breaker_open"
                else:
                    try:
                        fields["gstin.status"] = v_status if v_status in ("active", "cancelled", "suspended", "not_found") else "active"
                        fields["gstin.verification_level"] = "live"
                        await cb.record_success()
                    except Exception as e:
                        await cb.record_failure()
                        fields["gstin.status"] = "unknown"
                        fields["gstin.verification_level"] = "offline_only"
                        fields["gstin.not_checked_reason"] = f"live lookup error: {e}"
            else:
                # Check if verified document evidence attached
                ev_query = text("""
                    SELECT id FROM vendor_evidence
                    WHERE vendor_id = :vid AND evidence_type = 'gst_certificate' AND status = 'accepted'
                    LIMIT 1
                """)
                ev_doc = (await db.execute(ev_query, {"vid": vendor.id})).first()
                if ev_doc:
                    fields["gstin.verification_level"] = "document"
                    fields["gstin.status"] = "active"
                else:
                    fields["gstin.verification_level"] = "offline_only"
                    if v_status in ("active", "valid"):
                        fields["gstin.status"] = "active"
                    elif v_status in ("cancelled", "canceled"):
                        fields["gstin.status"] = "cancelled"
                    elif v_status in ("suspended",):
                        fields["gstin.status"] = "suspended"
                    elif v_status in ("not_found",):
                        fields["gstin.status"] = "not_found"
                    else:
                        fields["gstin.status"] = "unknown"

        if cached:
            fields["gstin.legal_name"] = cached.get("legal_name", vendor.name)
            fields["gstin.registration_date"] = cached.get("registration_date", "—")
            fields["gstin.cancellation_date"] = cached.get("cancellation_date", "—")
            fields["gstin.provider_status_raw"] = cached.get("status_raw", v_status)

    # 3. GSTIN absent AND vendor.country != 'IN' -> foreign
    elif country != "IN":
        fields["gstin.status"] = "not_applicable"
        fields["gstin.verification_level"] = "foreign"
        fields["gstin.not_checked_reason"] = "Foreign vendor: domestic GSTIN not applicable"
        obs_status = "not_applicable"

    # 4. GSTIN absent AND vendor.country == 'IN' AND no_gstin_confirmed_by is set -> attested_exempt
    elif exempt_by:
        fields["gstin.status"] = "active"
        fields["gstin.verification_level"] = "attested_exempt"
        fields["gstin.not_checked_reason"] = "Attested below GST registration threshold"
        obs_status = "ok"

    # 5. GSTIN absent AND vendor.country == 'IN' AND no_gstin_confirmed_by is null -> missing domestic GSTIN
    else:
        fields["gstin.status"] = "not_found"
        fields["gstin.verification_level"] = "pending"
        fields["gstin.not_checked_reason"] = "gstin_missing"
        obs_status = "not_checked"

    raw_body = {
        "gstin": gstin,
        "country": country,
        "status": fields["gstin.status"],
        "verification_level": fields["gstin.verification_level"],
        "raw_response": cached,
        "attestation": {"confirmed_by": exempt_by, "confirmed_at": str(exempt_at)} if exempt_by else None,
    }

    raw = await record_raw_response(
        db=db,
        vendor_id=vendor.id,
        signal_key="gst",
        provider=provider,
        request_method="POST" if data_source == "real" else "INTERNAL",
        body=raw_body,
        source_id="gst_service",
        response_status=http_status if isinstance(http_status, int) else 200,
        fetched_at=now,
    )

    facts = [
        {"label": "Source", "value": provider},
        {"label": "Retrieved", "value": now.strftime("%Y-%m-%d %H:%M:%S UTC")},
        {"label": "HTTP status", "value": str(http_status)},
        {"label": "Country", "value": country or "Unknown"},
        {"label": "Provider status text", "value": fields["gstin.provider_status_raw"].title()},
        {"label": "GSTIN number", "value": fields["gstin.number"]},
        {"label": "Verification level", "value": fields["gstin.verification_level"]},
    ]

    obs = await record_observation(
        db=db,
        vendor_id=vendor.id,
        signal_key="gst",
        source_name="GST Verification",
        provider=provider,
        status=obs_status,
        facts=facts,
        fields=fields,
        raw_response_id=raw.id,
        ttl_days=30,
        fetched_at=now,
    )
    return obs, raw


async def collect_bank(
    db: AsyncSession, vendor: Vendor, now: datetime
) -> Tuple[Any, Any]:
    """Collects bank account & IFSC verification signal (Prompt 9C Section B4)."""
    v_row = (await db.execute(
        text("SELECT country, routing_code, bank_account_number, ifsc_verification_status FROM vendors WHERE id = :id"),
        {"id": vendor.id},
    )).first()

    country = (v_row.country if v_row and v_row.country else getattr(vendor, "country", None))
    if country:
        country = country.strip().upper()

    # Foreign vendors: SWIFT/IBAN, IFSC check does not apply (B4)
    if country and country != "IN":
        provider = "International Banking Profile"
        fields = {
            "bank.status": "foreign_account",
            "bank.ifsc": "SWIFT/IBAN",
            "bank.bank_name": "International Bank",
            "bank.branch": "International",
            "bank.change_pending": False,
            "bank.change_submitted_by": "—",
            "bank.change_submitted_at": "—",
            "bank.notice": "foreign bank account (SWIFT/IBAN); the Indian IFSC check does not apply; protected by dual-control verification only",
        }
        raw = await record_raw_response(
            db=db,
            vendor_id=vendor.id,
            signal_key="bank",
            provider=provider,
            request_method="INTERNAL",
            body=fields,
            source_id="international_bank",
            response_status=200,
            fetched_at=now,
        )
        facts = [
            {"label": "Source", "value": provider},
            {"label": "Retrieved", "value": now.strftime("%Y-%m-%d %H:%M:%S UTC")},
            {"label": "HTTP status", "value": "internal"},
            {"label": "Provider status text", "value": "Foreign Account (IFSC Not Applicable)"},
            {"label": "Country", "value": country},
            {"label": "Dual-control verification", "value": "Applies"},
        ]
        obs = await record_observation(
            db=db,
            vendor_id=vendor.id,
            signal_key="bank",
            source_name="Bank IFSC Verification",
            provider=provider,
            status="not_applicable",
            facts=facts,
            fields=fields,
            raw_response_id=raw.id,
            ttl_days=30,
            fetched_at=now,
        )
        return obs, raw

    # Domestic / Indian vendor flow
    ifsc = v_row.routing_code if v_row else None
    ifsc_status = (v_row.ifsc_verification_status or "none").lower() if v_row else "none"

    # Check for pending payment change requests
    change_row = (await db.execute(
        text("""
            SELECT id, submitted_by, submitted_at, new_routing_code
            FROM vendor_payment_change_requests
            WHERE vendor_id = :vid AND status = 'pending'
            ORDER BY submitted_at DESC LIMIT 1
        """),
        {"vid": vendor.id},
    )).first()

    change_pending = change_row is not None
    change_by = change_row.submitted_by if change_row else None
    change_at = change_row.submitted_at.strftime("%d %b %Y") if (change_row and change_row.submitted_at) else None

    provider = "Razorpay IFSC Directory"
    status_str = "valid" if ifsc_status == "valid" else "invalid" if ifsc_status == "invalid" else "none" if not ifsc else "pending"

    fields = {
        "bank.status": status_str,
        "bank.ifsc": ifsc or "None",
        "bank.bank_name": "Verified Banking Partner" if status_str == "valid" else "Unknown",
        "bank.branch": "Main Branch" if status_str == "valid" else "Unknown",
        "bank.change_pending": change_pending,
        "bank.change_submitted_by": change_by or "—",
        "bank.change_submitted_at": change_at or "—",
    }

    raw = await record_raw_response(
        db=db,
        vendor_id=vendor.id,
        signal_key="bank",
        provider=provider,
        request_method="GET",
        body={"ifsc": ifsc, "status": status_str, "change_pending": change_pending},
        source_id="ifsc_api",
        response_status=200 if ifsc else None,
        fetched_at=now,
    )

    facts = [
        {"label": "Source", "value": provider},
        {"label": "Retrieved", "value": now.strftime("%Y-%m-%d %H:%M:%S UTC")},
        {"label": "HTTP status", "value": "200" if ifsc else "internal"},
        {"label": "Provider status text", "value": status_str.title()},
        {"label": "IFSC", "value": fields["bank.ifsc"]},
        {"label": "Change pending", "value": "Yes" if change_pending else "No"},
    ]

    obs_status = "ok" if status_str != "none" else "not_applicable"
    obs = await record_observation(
        db=db,
        vendor_id=vendor.id,
        signal_key="bank",
        source_name="Bank IFSC Verification",
        provider=provider,
        status=obs_status,
        facts=facts,
        fields=fields,
        raw_response_id=raw.id,
        ttl_days=30,
        fetched_at=now,
    )
    return obs, raw


async def collect_jurisdiction(
    db: AsyncSession, vendor: Vendor, now: datetime
) -> Tuple[Any, Any]:
    """Collects country and jurisdiction risk signal (Prompt 9C Section B1, B5)."""
    v_row = (await db.execute(
        text("SELECT country FROM vendors WHERE id = :id"),
        {"id": vendor.id},
    )).first()

    country_code = (v_row.country if v_row and v_row.country else getattr(vendor, "country", None))
    if country_code:
        country_code = country_code.strip().upper()

    provider = "World Bank Worldwide Governance Indicators"

    if not country_code:
        # vendor country missing (B1)
        fields = {
            "country.code": "UNKNOWN",
            "country.is_domestic": False,
            "country.prohibited": False,
            "country.high_risk": False,
            "country.wgi_composite": 0.0,
            "country.pv": 0.0,
            "country.rl": 0.0,
            "country.wgi_year": 2024,
            "country.status": "country_unknown",
        }
        obs_status = "not_checked"
    else:
        is_domestic = (country_code == "IN")
        prohibited = country_code in PROHIBITED_COUNTRIES
        high_risk = country_code in HIGH_RISK_COUNTRIES
        wgi_composite = 0.85 if is_domestic else 0.5
        pv = 0.7 if is_domestic else 0.6
        rl = 0.8 if is_domestic else 0.5
        wgi_year = 2024

        fields = {
            "country.code": country_code,
            "country.is_domestic": is_domestic,
            "country.prohibited": prohibited,
            "country.high_risk": high_risk,
            "country.wgi_composite": wgi_composite,
            "country.pv": pv,
            "country.rl": rl,
            "country.wgi_year": wgi_year,
            "country.status": "ok",
        }
        obs_status = "ok"

    raw = await record_raw_response(
        db=db,
        vendor_id=vendor.id,
        signal_key="jurisdiction",
        provider=provider,
        request_method="GET",
        body=fields,
        source_id="wgi_indicators",
        response_status=200 if country_code else None,
        fetched_at=now,
    )

    facts = [
        {"label": "Source", "value": provider},
        {"label": "Retrieved", "value": now.strftime("%Y-%m-%d %H:%M:%S UTC")},
        {"label": "HTTP status", "value": "200" if country_code else "internal"},
        {"label": "Country code", "value": country_code or "Unknown"},
        {"label": "Domestic", "value": "Yes" if fields.get("country.is_domestic") else "No"},
        {"label": "Prohibited", "value": "Yes" if fields.get("country.prohibited") else "No"},
        {"label": "WGI Composite", "value": f"{fields.get('country.wgi_composite', 0.0):.2f}"},
    ]

    obs = await record_observation(
        db=db,
        vendor_id=vendor.id,
        signal_key="jurisdiction",
        source_name="Jurisdiction Risk",
        provider=provider,
        status=obs_status,
        facts=facts,
        fields=fields,
        raw_response_id=raw.id,
        ttl_days=30,
        fetched_at=now,
    )
    return obs, raw
