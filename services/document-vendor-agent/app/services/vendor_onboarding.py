"""Vendor onboarding and profile validation (BR-4).

Finance/admin onboard a vendor from a form. The profile is checked before
anything is saved:
  errors (block):   missing name, duplicate of an existing vendor (same
                    GSTIN, or a name that fuzzy-matches one), malformed
                    GSTIN (format + check digit), malformed / unknown IFSC,
                    bad email / phone / account number
  warnings (confirm): a look-alike name (could be an impostor), no GSTIN,
                    IFSC lookup unavailable right now
Bank details are never written straight onto the vendor: they go through
the existing two-person verification (vendor_payment_service), so a second
person confirms them before the vendor can be paid.
"""
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from rapidfuzz import fuzz
from sqlalchemy import select

from app.config import load_vendor_matching_config
from app.models import Vendor
from app.services.audit import write_audit_log
from app.services.gstin_service import validate_gstin_offline
from app.services.vendor_matching import normalize_vendor_name

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
_PHONE = re.compile(r"^\+?[0-9][0-9\s\-()]{6,18}$")
_IFSC = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
_ACCOUNT = re.compile(r"^[0-9]{9,18}$")
LOOKALIKE_MIN = 70


@dataclass
class VendorProfile:
    name: str
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    address: Optional[str] = None
    category: Optional[str] = None
    gstin: Optional[str] = None
    bank_account_number: Optional[str] = None
    routing_code: Optional[str] = None
    payment_beneficiary_name: Optional[str] = None


@dataclass
class ProfileCheck:
    errors: list = field(default_factory=list)      # [{"field", "message"}]
    warnings: list = field(default_factory=list)    # [{"code", "field", "message"}]

    @property
    def ok(self) -> bool:
        return not self.errors


def _clean(v: Optional[str]) -> Optional[str]:
    v = (v or "").strip()
    return v or None


def normalise(p: VendorProfile) -> VendorProfile:
    return VendorProfile(
        name=(p.name or "").strip(),
        contact_email=_clean(p.contact_email.lower() if p.contact_email else None),
        contact_phone=_clean(p.contact_phone),
        address=_clean(p.address),
        category=_clean(p.category),
        gstin=_clean(p.gstin.upper().replace(" ", "") if p.gstin else None),
        bank_account_number=_clean(re.sub(r"\s", "", p.bank_account_number) if p.bank_account_number else None),
        routing_code=_clean(p.routing_code.upper().replace(" ", "") if p.routing_code else None),
        payment_beneficiary_name=_clean(p.payment_beneficiary_name),
    )


def check_fields(p: VendorProfile) -> ProfileCheck:
    """Checks that need no database or network."""
    c = ProfileCheck()
    if len(p.name) < 2:
        c.errors.append({"field": "name", "message": "Vendor name is required."})
    if p.contact_email and not _EMAIL.match(p.contact_email):
        c.errors.append({"field": "contact_email", "message": "Not a valid email address."})
    if p.contact_phone and not _PHONE.match(p.contact_phone):
        c.errors.append({"field": "contact_phone", "message": "Not a valid phone number."})
    if p.gstin:
        valid, reason = validate_gstin_offline(p.gstin)
        if not valid:
            c.errors.append({"field": "gstin", "message": reason})
    else:
        c.warnings.append({"code": "no_gstin", "field": "gstin",
                           "message": "No GSTIN: only allowed for unregistered or foreign vendors."})
    bank = [p.bank_account_number, p.routing_code]
    if any(bank) and not all(bank):
        c.errors.append({"field": "routing_code" if p.bank_account_number else "bank_account_number",
                         "message": "Give both the account number and the IFSC, or neither."})
    if p.bank_account_number and not _ACCOUNT.match(p.bank_account_number):
        c.errors.append({"field": "bank_account_number", "message": "Account number must be 9–18 digits."})
    if p.routing_code and not _IFSC.match(p.routing_code):
        c.errors.append({"field": "routing_code", "message": "IFSC must look like HDFC0001234 (4 letters, 0, 6 characters)."})
    return c


def compare_names(name: str, existing: list) -> tuple[Optional[object], float]:
    """Closest existing vendor and its similarity (0-100)."""
    norm = normalize_vendor_name(name)
    best, best_score = None, 0.0
    for v in existing:
        score = fuzz.token_sort_ratio(norm, v.normalized_name or normalize_vendor_name(v.name))
        if score > best_score:
            best, best_score = v, score
    return best, best_score


async def validate_profile(db, profile: VendorProfile, check_ifsc=None) -> ProfileCheck:
    """Full check: fields, duplicates / look-alikes, IFSC lookup."""
    p = normalise(profile)
    c = check_fields(p)
    existing = list((await db.execute(select(Vendor).where(Vendor.status != "offboarded"))).scalars().all())
    if p.gstin and any((v.gstin or "").upper() == p.gstin for v in existing):
        same = next(v for v in existing if (v.gstin or "").upper() == p.gstin)
        c.errors.append({"field": "gstin", "message": f"Already onboarded as “{same.name}” (same GSTIN).",
                         "vendor_id": str(same.id)})
    if p.name:
        closest, score = compare_names(p.name, existing)
        threshold = load_vendor_matching_config().get("fuzzy_match_threshold", 88)
        if closest is not None and score >= threshold:
            c.errors.append({"field": "name", "message": f"Duplicate of existing vendor “{closest.name}”.",
                             "vendor_id": str(closest.id)})
        elif closest is not None and score >= LOOKALIKE_MIN:
            c.warnings.append({"code": "lookalike", "field": "name", "vendor_id": str(closest.id),
                               "message": f"Looks like “{closest.name}” ({score:.0f}% similar) — "
                                          "check it isn't an impostor before onboarding."})
    if p.routing_code and _IFSC.match(p.routing_code) and check_ifsc is not None:
        result = await check_ifsc(p.routing_code)
        status = getattr(result.status, "value", result.status)
        if status == "invalid":
            c.errors.append({"field": "routing_code", "message": f"IFSC {p.routing_code} does not exist."})
        elif status == "pending":
            c.warnings.append({"code": "ifsc_unverified", "field": "routing_code",
                               "message": "Couldn't reach the IFSC directory; it will be checked again at verification."})
    return c


def required_confirmations(check: ProfileCheck) -> set:
    return {w["code"] for w in check.warnings if w["code"] in ("lookalike", "no_gstin")}


async def onboard_vendor(db, kafka_producer, profile: VendorProfile, onboarded_by: str,
                         confirmed: set, no_gstin_reason: Optional[str], check_ifsc=None):
    """Validates, then creates the vendor. Returns (vendor | None, check)."""
    from app.services.vendor_payment_service import submit_payment_change
    p = normalise(profile)
    check = await validate_profile(db, p, check_ifsc)
    required = required_confirmations(check)
    missing = required - set(confirmed)
    if "no_gstin" in required and not _clean(no_gstin_reason):
        missing.add("no_gstin")  # confirming isn't enough without saying why
    if not check.ok or missing:
        return None, check, missing
    now = datetime.now(timezone.utc)
    vendor = Vendor(
        id=str(uuid.uuid4()), name=p.name, normalized_name=normalize_vendor_name(p.name), status="active",
        contact_email=p.contact_email, contact_phone=p.contact_phone, address=p.address, category=p.category,
        gstin=p.gstin, gstin_verification_status="format_valid" if p.gstin else "unverified",
        no_gstin_confirmed_by=None if p.gstin else onboarded_by, no_gstin_confirmed_at=None if p.gstin else now,
        created_at=now, updated_at=now,
    )
    db.add(vendor)
    await db.flush()
    await write_audit_log(db, entity_type="vendor", entity_id=vendor.id, action="vendor_onboarded", payload={
        "onboarded_by": onboarded_by, "gstin": p.gstin, "no_gstin_reason": _clean(no_gstin_reason),
        "warnings_confirmed": sorted(confirmed), "warnings": [w["code"] for w in check.warnings],
    })
    if p.bank_account_number:
        # Never live straight away: a second person verifies (dual control).
        await submit_payment_change(
            db, kafka_producer, vendor, new_bank_account=p.bank_account_number, new_routing=p.routing_code,
            new_beneficiary=p.payment_beneficiary_name or p.name, submitted_by=onboarded_by, source="onboarding",
        )
    await db.commit()
    return vendor, check, set()
