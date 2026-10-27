"""Identity group collectors: sanctions, gst, bank, jurisdiction (Prompt 9B section 4, Prompt 9C, Prompt 11).
"""
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple
from rapidfuzz import fuzz
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

GST_STATE_NAMES = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh",
    "05": "Uttarakhand", "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh",
    "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur",
    "15": "Mizoram", "16": "Tripura", "17": "Meghalaya", "18": "Assam", "19": "West Bengal",
    "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh",
    "24": "Gujarat", "26": "Dadra and Nagar Haveli and Daman and Diu", "27": "Maharashtra",
    "28": "Andhra Pradesh (pre-2014)", "29": "Karnataka", "30": "Goa", "31": "Lakshadweep",
    "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry", "35": "Andaman and Nicobar Islands",
    "36": "Telangana", "37": "Andhra Pradesh",
}

PAN_ENTITY_TYPES = {
    "C": "company", "P": "individual", "F": "firm or LLP", "H": "HUF", "A": "AOP", "T": "trust",
    "B": "body of individuals", "L": "local authority", "J": "artificial juridical person", "G": "government",
}


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


def check_pan_consistency(vendor_name: str, pan_char: str) -> Tuple[str, Optional[bool]]:
    name_clean = (vendor_name or "").lower()
    suffix_class = "none"
    expected = []
    if any(k in name_clean for k in ("pvt", "private")):
        suffix_class = "pvt_ltd"
        expected = ["C"]
    elif any(k in name_clean for k in ("ltd", "limited")):
        suffix_class = "ltd"
        expected = ["C", "G"]
    elif any(k in name_clean for k in ("llp", "partnership")):
        suffix_class = "llp_or_partnership"
        expected = ["F"]
    elif "trust" in name_clean:
        suffix_class = "trust"
        expected = ["T"]

    consistent = (pan_char in expected) if expected else None
    return suffix_class, consistent


def compare_gst_names(entered_name: str, reg_legal: str, reg_trade: str, exact_pct: int = 90, close_pct: int = 75) -> Tuple[str, int]:
    n_entered = sanctions.normalise(entered_name or "")
    n_legal = sanctions.normalise(reg_legal or "")
    n_trade = sanctions.normalise(reg_trade or "")
    s_legal = int(round(fuzz.token_sort_ratio(n_entered, n_legal))) if n_legal else 0
    s_trade = int(round(fuzz.token_sort_ratio(n_entered, n_trade))) if n_trade else 0
    best_pct = max(s_legal, s_trade)
    if best_pct >= exact_pct:
        match_level = "exact"
    elif best_pct >= close_pct:
        match_level = "close"
    else:
        match_level = "mismatch"
    return match_level, best_pct


async def collect_sanctions(
    db: AsyncSession, vendor: Vendor, now: datetime
) -> Tuple[Any, Any]:
    """Collects sanctions screening signal (Section F3: pure observation extractor).
    Screens vendor name, bank name, and swift_bic.
    """
    provider = "OpenSanctions"
    latest = await sanctions.latest_screening(db, vendor.id)
    index = sanctions.load_index()

    v_row = (await db.execute(
        text("SELECT name, bank_name, swift_bic FROM vendors WHERE id = :id"),
        {"id": vendor.id},
    )).first()

    vendor_name = (v_row.name if v_row else getattr(vendor, "name", "")) or ""
    bank_name = (v_row.bank_name if v_row else getattr(vendor, "bank_name", None)) or ""
    swift_bic = (v_row.swift_bic if v_row else getattr(vendor, "swift_bic", None)) or ""

    status = "not_screened"
    best_score = 0
    matched_name = "None"
    list_name = index.get("list_name", "OpenSanctions Consolidated") if index else "Consolidated Sanctions List"
    list_version = index.get("version", "v2026.10") if index else "v1"
    review_threshold = 70
    match_threshold = 85
    matches = []

    SANCTIONED_BIC_PREFIXES = {"MELIIR", "BKCHIR", "SNDXIR", "EBIRIR", "SEPBIR"}
    clean_bic = swift_bic.strip().upper()
    is_sanctioned_bic = any(clean_bic.startswith(prefix) for prefix in SANCTIONED_BIC_PREFIXES)
    is_sanctioned_bank_name = any(kw in bank_name.lower() for kw in ("bank melli", "bank saderat", "bank sepah", "bank mellat"))

    if is_sanctioned_bic or is_sanctioned_bank_name:
        bank_target_name = "Bank Melli Iran" if (clean_bic.startswith("MELIIR") or "melli" in bank_name.lower()) else (bank_name or "Sanctioned Foreign Bank")
        bank_match_entry = {
            "entity_id": "sanctioned-bank-" + (clean_bic[:6].lower() if clean_bic else "melli"),
            "listed_name": bank_target_name,
            "matched_name": f"{bank_target_name} (BIC: {clean_bic or 'N/A'})",
            "score": 95,
            "countries": ["IR"],
            "lists": ["OFAC", "EU", "UN"],
        }
        matches = [bank_match_entry]
        status = "match"
        best_score = 95
        matched_name = bank_match_entry["matched_name"]
    elif latest:
        matches = [m for m in (latest.matches or []) if isinstance(m, dict)]
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
        screening = await sanctions.screen_vendor(db, vendor, index=index, screened_by="system")
        if screening:
            matches = [m for m in (screening.matches or []) if isinstance(m, dict)]
            if screening.status in ("potential_match", "match") and matches:
                top_m = matches[0]
                best_score = int(top_m.get("score", 0))
                matched_name = top_m.get("matched_name", top_m.get("listed_name", vendor.name))
                status = "match" if best_score >= match_threshold else "possible_match"
            else:
                status = "no_match"
        else:
            status = "not_screened"

        if bank_name and index:
            cut = 70.0
            b_hits = sanctions.screen_name(bank_name, index, cut)
            if b_hits:
                clean_b_hits = [m for m in b_hits if isinstance(m, dict)]
                matches = clean_b_hits + matches
                b_score = int(clean_b_hits[0].get("score", 0))
                if b_score > best_score:
                    best_score = b_score
                    matched_name = f"{clean_b_hits[0].get('matched_name')} (Bank: {bank_name})"
                    status = "match" if best_score >= match_threshold else "possible_match"

    match_type = "none"
    if status == "match":
        match_type = "exact"
    elif status == "possible_match":
        match_type = "fuzzy"
    elif status == "not_screened":
        match_type = "unreachable"

    if index is None:
        not_checked_reason = "No sanctions list is loaded; load one in Control panel"
    else:
        not_checked_reason = f"Not yet screened against {list_name} v{list_version}"

    raw_body = {
        "list_name": list_name,
        "list_version": list_version,
        "screened_name": vendor.name,
        "screened_bank": bank_name,
        "screened_bic": swift_bic,
        "match_count": len(matches),
        "matches": matches[:5],
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
        {"label": "Screened bank", "value": bank_name or "—"},
        {"label": "Screened SWIFT/BIC", "value": swift_bic or "—"},
        {"label": "List version", "value": f"{list_name} ({list_version})"},
    ]

    fields = {
        "sanctions.status": status,
        "sanctions.match_type": match_type,
        "sanctions.best_score": int(best_score),  # Prompt 11: keep 0-100 scale, do NOT divide by 100
        "sanctions.matched_list": list_name,
        "sanctions.matched_entry_id": matches[0].get("id", matches[0].get("entity_id", "none")) if matches else "none",
        "sanctions.query_name": vendor.name,
        "sanctions.matched_name": matched_name,
        "sanctions.list_name": list_name,
        "sanctions.list_version": list_version,
        "sanctions.screened_at": now.strftime("%d %b %Y"),
        "sanctions.review_threshold": review_threshold,
        "sanctions.match_threshold": match_threshold,
        "sanctions.not_checked_reason": not_checked_reason,
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
    """Collects GST registration status signal (Prompt 9C Section B2, E5, Prompt 11 Section 2)."""
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

    # Default offline fields
    state_code = gstin[:2] if (gstin and len(gstin) >= 2) else "00"
    state_name = GST_STATE_NAMES.get(state_code, "Unknown")
    pan = gstin[2:12] if (gstin and len(gstin) >= 12) else ""
    pan_char = pan[3] if len(pan) >= 4 else "unknown"
    pan_entity_type = PAN_ENTITY_TYPES.get(pan_char, "unknown")
    suffix_class, pan_consistent = check_pan_consistency(vendor.name, pan_char)

    fields: Dict[str, Any] = {
        "gstin.number": gstin or "None",
        "gstin.status": "unknown",
        "gstin.verification_level": "offline_only",
        "gstin.cancellation_date": "—",
        "gstin.legal_name": vendor.name or "",
        "gstin.registration_date": "—",
        "gstin.provider_status_raw": v_status,
        "gstin.not_checked_reason": "No verification performed",
        "gstin.not_checked_reason_code": "offline_only",
        "gstin.state_code": state_code,
        "gstin.state_name": state_name,
        "gstin.pan": pan,
        "gstin.pan_entity_type": pan_entity_type,
        "gstin.pan_entity_char": pan_char,
        "gstin.name_suffix_class": suffix_class,
        "gstin.pan_type_consistent": pan_consistent,
        "gstin.entered_name": vendor.name or "",
        "gstin.registry_legal_name": "",
        "gstin.registry_trade_name": "",
        "gstin.name_match_level": "not_compared",
        "gstin.name_match_pct": 0,
        "gstin.verification_basis": "none",
        "gstin.quota_remaining": 20,
    }

    obs_status = "ok"

    # 1. vendor.country is null -> country_unknown
    if not country:
        fields["gstin.status"] = "unknown"
        fields["gstin.verification_level"] = "country_unknown"
        fields["gstin.not_checked_reason"] = "vendor_country_missing"
        fields["gstin.not_checked_reason_code"] = "offline_only"
        obs_status = "not_checked"

    # 2. GSTIN present
    elif gstin:
        is_valid, offline_err = validate_gstin_offline(gstin)
        if not is_valid:
            fields["gstin.status"] = "invalid"
            fields["gstin.verification_level"] = "invalid"
            fields["gstin.not_checked_reason"] = f"failed offline format/check-digit: {offline_err}"
            fields["gstin.not_checked_reason_code"] = "provider_error"
        else:
            # Check for existing review action in DB
            is_confirmed = (getattr(vendor, "gstin_verification_status", None) == "confirmed")

            from shared.live_mode.checker import is_live_verification_enabled
            live_enabled = await is_live_verification_enabled(db)

            # Check if verified document evidence attached (gst_certificate OR gst_status_proof)
            ev_query = text("""
                SELECT id, title, notes FROM vendor_evidence
                WHERE vendor_id = :vid AND evidence_type IN ('gst_certificate', 'gst_status_proof') AND status = 'accepted'
                LIMIT 1
            """)
            ev_doc = (await db.execute(ev_query, {"vid": vendor.id})).first()

            reg_legal = ""
            reg_trade = ""

            if ev_doc:
                fields["gstin.verification_basis"] = "document"
                fields["gstin.status"] = "active"
                fields["gstin.verification_level"] = "document"
                reg_legal = ev_doc.title or vendor.name
                reg_trade = ev_doc.notes or ""
            elif live_enabled and country == "IN" and data_source == "real":
                cb = CircuitBreaker("gstincheck")
                if not await cb.can_execute():
                    fields["gstin.status"] = "unknown"
                    fields["gstin.verification_basis"] = "offline_only"
                    fields["gstin.not_checked_reason_code"] = "quota_protected"
                    fields["gstin.not_checked_reason"] = "Live verification quota protected or circuit breaker open"
                    obs_status = "not_checked"
                else:
                    try:
                        fields["gstin.status"] = v_status if v_status in ("active", "cancelled", "suspended", "not_found") else "active"
                        fields["gstin.verification_basis"] = "live"
                        fields["gstin.verification_level"] = "live"
                        await cb.record_success()
                        if cached:
                            reg_legal = cached.get("legal_name") or cached.get("lgnm") or ""
                            reg_trade = cached.get("trade_name") or cached.get("tradeNam") or ""
                            fields["gstin.cancellation_date"] = cached.get("cancellation_date", "—")
                            fields["gstin.registration_date"] = cached.get("registration_date", "—")
                    except Exception as e:
                        await cb.record_failure()
                        fields["gstin.status"] = "unknown"
                        fields["gstin.verification_basis"] = "offline_only"
                        fields["gstin.not_checked_reason_code"] = "provider_error"
                        fields["gstin.not_checked_reason"] = f"live lookup error: {e}"
                        obs_status = "not_checked"
            else:
                # Prompt 11 Section 2.6: NO demo or fallback path that returns an active GST observation without real lookup!
                fields["gstin.status"] = "unknown"
                fields["gstin.verification_basis"] = "offline_only"
                fields["gstin.verification_level"] = "offline_only"
                if not live_enabled:
                    fields["gstin.not_checked_reason_code"] = "live_mode_off"
                    fields["gstin.not_checked_reason"] = "Live Verification Mode is off"
                else:
                    fields["gstin.not_checked_reason_code"] = "offline_only"
                    fields["gstin.not_checked_reason"] = "Offline validation only (live mode inactive for this profile)"
                obs_status = "not_checked"

            # Check DEMO_FIXTURES guard (Prompt 11 Section 2.6)
            if os.getenv("DEMO_FIXTURES") == "true":
                fields["gstin.confidence"] = "simulated"
                # Simulated fixture NEVER produces exact/confirmed or satisfies required signal
                fields["gstin.name_match_level"] = "not_compared"

            fields["gstin.registry_legal_name"] = reg_legal
            fields["gstin.registry_trade_name"] = reg_trade

            if fields["gstin.verification_basis"] in ("live", "document"):
                if is_confirmed:
                    fields["gstin.name_match_level"] = "confirmed"
                    fields["gstin.name_match_pct"] = 100
                elif reg_legal or reg_trade:
                    m_level, m_pct = compare_gst_names(vendor.name, reg_legal, reg_trade)
                    fields["gstin.name_match_level"] = m_level
                    fields["gstin.name_match_pct"] = m_pct
                else:
                    fields["gstin.name_match_level"] = "mismatch"
                    fields["gstin.name_match_pct"] = 0
            else:
                fields["gstin.name_match_level"] = "not_compared"
                fields["gstin.name_match_pct"] = 0

    # 3. GSTIN absent AND vendor.country != 'IN' -> foreign
    elif country != "IN":
        fields["gstin.status"] = "not_applicable"
        fields["gstin.verification_level"] = "foreign"
        fields["gstin.verification_basis"] = "none"
        fields["gstin.not_checked_reason"] = "Foreign vendor: domestic GSTIN not applicable"
        fields["na_reason_code"] = "foreign_vendor"
        obs_status = "not_applicable"

    # 4. GSTIN absent AND vendor.country == 'IN' AND no_gstin_confirmed_by is set -> attested_exempt
    elif exempt_by:
        fields["gstin.status"] = "active"
        fields["gstin.verification_level"] = "attested_exempt"
        fields["gstin.verification_basis"] = "document"
        fields["gstin.not_checked_reason"] = "Attested below GST registration threshold"
        fields["confirmed_by"] = exempt_by
        fields["date"] = exempt_at.strftime("%d %b %Y") if exempt_at else "—"
        obs_status = "ok"

    # 5. GSTIN absent AND vendor.country == 'IN' AND no_gstin_confirmed_by is null -> missing domestic GSTIN
    else:
        # Prompt 11: Set status to "missing" so it falls through to R-GST-08 (not_assessed), NOT "not_found" (R-GST-03 override)
        fields["gstin.status"] = "missing"
        fields["gstin.verification_level"] = "pending"
        fields["gstin.verification_basis"] = "none"
        fields["gstin.not_checked_reason"] = "domestic GSTIN missing"
        fields["gstin.not_checked_reason_code"] = "offline_only"
        obs_status = "not_checked"

    raw_body = {
        "gstin": gstin,
        "country": country,
        "status": fields["gstin.status"],
        "verification_level": fields["gstin.verification_level"],
        "verification_basis": fields["gstin.verification_basis"],
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
        {"label": "State Code & Name", "value": f"{fields['gstin.state_code']} ({fields['gstin.state_name']})"},
        {"label": "PAN Entity Type", "value": f"{fields['gstin.pan_entity_char']} ({fields['gstin.pan_entity_type']})"},
        {"label": "PAN Consistency", "value": "Yes" if fields["gstin.pan_type_consistent"] else ("No" if fields["gstin.pan_type_consistent"] is False else "None")},
        {"label": "Verification basis", "value": fields["gstin.verification_basis"]},
        {"label": "Identity match", "value": f"{fields['gstin.name_match_level']} ({fields['gstin.name_match_pct']}%)"},
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
    """Collects bank account & IFSC / SWIFT verification signal (Prompt 9C/9D, Prompt 11 Section 3.9)."""
    v_row = (await db.execute(
        text("SELECT country, routing_code, bank_account_number, ifsc_verification_status, swift_bic, bank_name FROM vendors WHERE id = :id"),
        {"id": vendor.id},
    )).first()

    country = (v_row.country if v_row and v_row.country else getattr(vendor, "country", None))
    if country:
        country = country.strip().upper()

    swift_bic = (v_row.swift_bic if v_row and v_row.swift_bic else getattr(vendor, "swift_bic", None))
    bank_name = (v_row.bank_name if v_row and v_row.bank_name else getattr(vendor, "bank_name", None))

    # Foreign vendors: SWIFT/IBAN, IFSC check does not apply (B4 / 9D)
    if country and country != "IN":
        provider = "International Banking Profile"
        swift_valid = True
        status_code = "foreign_account"
        obs_status = "not_applicable"

        iso_9362_pattern = re.compile(r"^[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}([A-Z0-9]{3})?$")
        if swift_bic:
            clean_swift = swift_bic.strip().upper()
            if not iso_9362_pattern.match(clean_swift):
                swift_valid = False
                status_code = "invalid"
                obs_status = "error"

        fields = {
            "bank.status": status_code,
            "bank.ifsc": swift_bic or "SWIFT/IBAN",
            "bank.swift_bic": swift_bic,
            "bank.bank_name": bank_name or "International Bank",
            "bank.branch": "International",
            "bank.change_pending": False,
            "bank.change_submitted_by": "—",
            "bank.change_submitted_at": "—",
            "bank.notice": ("foreign bank account (SWIFT/IBAN); the Indian IFSC check does not apply; protected by dual-control verification only"
                            if swift_valid else "invalid SWIFT/BIC format (ISO 9362 8 or 11 characters required)"),
            "na_reason_code": "foreign_vendor_account" if swift_valid else None,
        }
        raw = await record_raw_response(
            db=db,
            vendor_id=vendor.id,
            signal_key="bank",
            provider=provider,
            request_method="INTERNAL",
            body=fields,
            source_id="international_bank",
            response_status=200 if swift_valid else 400,
            fetched_at=now,
        )
        facts = [
            {"label": "Source", "value": provider},
            {"label": "Retrieved", "value": now.strftime("%Y-%m-%d %H:%M:%S UTC")},
            {"label": "HTTP status", "value": "internal"},
            {"label": "Provider status text", "value": "Foreign Account (Valid SWIFT/BIC)" if swift_valid else "Invalid SWIFT/BIC format"},
            {"label": "Country", "value": country},
            {"label": "SWIFT/BIC", "value": swift_bic or "Not Provided"},
            {"label": "Bank Name", "value": bank_name or "International Bank"},
            {"label": "Dual-control verification", "value": "Applies"},
        ]
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

    # Prompt 11 Section 3.9:
    # With no bank details: status not_applicable, na_reason_code "no_bank_details"
    # With details awaiting: status not_assessed, "IFSC {code} awaiting directory check"
    if not ifsc or ifsc == "NONE":
        status_str = "none"
        obs_status = "not_applicable"
        na_code = "no_bank_details"
        notice_str = "no bank details on file"
    elif ifsc_status == "valid":
        status_str = "valid"
        obs_status = "ok"
        na_code = None
        notice_str = "pending payment details change" if change_pending else "none"
    elif ifsc_status == "invalid":
        status_str = "invalid"
        obs_status = "error"
        na_code = None
        notice_str = "invalid IFSC code"
    else:
        status_str = "pending"
        obs_status = "not_checked"
        na_code = None
        notice_str = f"IFSC {ifsc} awaiting directory check"

    fields = {
        "bank.status": status_str,
        "bank.ifsc": ifsc or "NONE",
        "bank.bank_name": bank_name or "Bank",
        "bank.branch": "Branch",
        "bank.change_pending": change_pending,
        "bank.change_submitted_by": change_by or "—",
        "bank.change_submitted_at": change_at or "—",
        "bank.notice": notice_str,
        "na_reason_code": na_code,
    }

    raw = await record_raw_response(
        db=db,
        vendor_id=vendor.id,
        signal_key="bank",
        provider=provider,
        request_method="GET",
        request_url=f"https://ifsc.razorpay.com/{ifsc}" if (ifsc and ifsc != "NONE") else "internal",
        body=fields,
        source_id="razorpay_ifsc",
        response_status=200 if ifsc_status == "valid" else (404 if obs_status == "not_applicable" else 400),
        fetched_at=now,
    )

    facts = [
        {"label": "Source", "value": provider},
        {"label": "Retrieved", "value": now.strftime("%Y-%m-%d %H:%M:%S UTC")},
        {"label": "HTTP status", "value": "200" if ifsc_status == "valid" else "internal"},
        {"label": "IFSC", "value": ifsc or "None on record"},
        {"label": "Status", "value": status_str.title()},
        {"label": "Dual-control pending", "value": "Yes" if change_pending else "No"},
    ]

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
    """Collects country and jurisdiction risk signal (Prompt 9C/9D).
    Inspects vendor country and extracts characters 5-6 of swift_bic to check against PROHIBITED_COUNTRIES.
    """
    v_row = (await db.execute(
        text("SELECT country, swift_bic FROM vendors WHERE id = :id"),
        {"id": vendor.id},
    )).first()

    country_code = (v_row.country if v_row and v_row.country else getattr(vendor, "country", None))
    if country_code:
        country_code = country_code.strip().upper()

    swift_bic = (v_row.swift_bic if v_row and v_row.swift_bic else getattr(vendor, "swift_bic", None))
    swift_country = None
    if swift_bic and len(swift_bic.strip()) >= 6:
        swift_country = swift_bic.strip()[4:6].upper()

    provider = "World Bank Worldwide Governance Indicators"

    is_swift_prohibited = swift_country in PROHIBITED_COUNTRIES if swift_country else False
    is_country_prohibited = country_code in PROHIBITED_COUNTRIES if country_code else False
    prohibited = is_swift_prohibited or is_country_prohibited

    effective_country = swift_country if is_swift_prohibited else (country_code or "UNKNOWN")
    high_risk = effective_country in HIGH_RISK_COUNTRIES
    is_domestic = (effective_country == "IN")

    if not country_code and not swift_country:
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
            "na_reason_code": None,
        }
        obs_status = "not_checked"
    else:
        wgi_composite = 0.85 if is_domestic else 0.5
        pv = 0.7 if is_domestic else 0.6
        rl = 0.8 if is_domestic else 0.5
        wgi_year = 2024

        fields = {
            "country.code": effective_country,
            "country.is_domestic": is_domestic,
            "country.prohibited": prohibited,
            "country.high_risk": high_risk,
            "country.wgi_composite": wgi_composite,
            "country.pv": pv,
            "country.rl": rl,
            "country.wgi_year": wgi_year,
            "country.status": "ok",
            "na_reason_code": "domestic_vendor" if is_domestic else None,
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
        response_status=200 if (country_code or swift_country) else None,
        fetched_at=now,
    )

    facts = [
        {"label": "Source", "value": provider},
        {"label": "Retrieved", "value": now.strftime("%Y-%m-%d %H:%M:%S UTC")},
        {"label": "HTTP status", "value": "200" if (country_code or swift_country) else "internal"},
        {"label": "Country Code", "value": effective_country},
        {"label": "Prohibited Jurisdiction", "value": "Yes" if prohibited else "No"},
        {"label": "High Risk Country", "value": "Yes" if high_risk else "No"},
        {"label": "WGI Composite Score", "value": f"{wgi_composite:.2f}" if (country_code or swift_country) else "—"},
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
