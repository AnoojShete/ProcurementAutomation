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


_SWIFT = re.compile(r"^[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}([A-Z0-9]{3})?$")

@dataclass
class VendorProfile:
    name: str
    country: Optional[str] = None
    inherent_tier: Optional[str] = None
    swift_bic: Optional[str] = None
    bank_name: Optional[str] = None
    website: Optional[str] = None
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
    ifsc_status: Optional[str] = None                  # valid | invalid | pending, when looked up

    @property
    def ok(self) -> bool:
        return not self.errors


def _clean(v: Optional[str]) -> Optional[str]:
    v = (v or "").strip()
    return v or None


def normalise(p: VendorProfile) -> VendorProfile:
    return VendorProfile(
        name=(p.name or "").strip(),
        country=_clean(p.country.upper() if p.country else None),
        inherent_tier=_clean(p.inherent_tier.lower() if p.inherent_tier else None),
        swift_bic=_clean(p.swift_bic.upper().replace(" ", "") if p.swift_bic else None),
        bank_name=_clean(p.bank_name),
        website=_clean(p.website),
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

    # Country validation (Prompt 9C B1, B5)
    if not p.country:
        c.errors.append({"field": "country", "message": "Vendor country is required."})
    else:
        from shared.iso_countries import is_valid_country_code
        if not is_valid_country_code(p.country):
            c.errors.append({"field": "country", "message": f"Country '{p.country}' must be a valid 2-letter uppercase ISO 3166-1 alpha-2 code."})

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
    if p.inherent_tier and p.inherent_tier not in ("low", "moderate", "high", "critical"):
        c.errors.append({"field": "inherent_tier", "message": "Inherent tier must be one of: low, moderate, high, critical."})

    if p.swift_bic and not _SWIFT.match(p.swift_bic):
        c.errors.append({"field": "swift_bic", "message": "SWIFT/BIC must be a valid 8 or 11 character ISO 9362 code."})

    # Foreign vendors: SWIFT/IBAN, Indian IFSC format check does not apply (B4 / 9D)
    if p.country and p.country != "IN":
        if p.bank_account_number and not (p.routing_code or p.swift_bic):
            c.errors.append({"field": "swift_bic", "message": "Provide a SWIFT/BIC code or routing code for foreign bank accounts."})
    else:
        bank = [p.bank_account_number, p.routing_code]
        if any(bank) and not all(bank):
            c.errors.append({"field": "routing_code" if p.bank_account_number else "bank_account_number",
                             "message": "Give both the account number and the IFSC, or neither."})
        if p.routing_code and not _IFSC.match(p.routing_code):
            c.errors.append({"field": "routing_code", "message": "IFSC must look like HDFC0001234 (4 letters, 0, 6 characters)."})
    if p.bank_account_number and not _ACCOUNT.match(p.bank_account_number):
        c.errors.append({"field": "bank_account_number", "message": "Account number must be 9–18 digits."})
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
        c.ifsc_status = status
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
        id=str(uuid.uuid4()), name=p.name, normalized_name=normalize_vendor_name(p.name), status="onboarding",
        country=p.country,
        inherent_tier=p.inherent_tier,
        swift_bic=p.swift_bic,
        bank_name=p.bank_name,
        website=p.website,
        contact_email=p.contact_email, contact_phone=p.contact_phone, address=p.address, category=p.category,
        gstin=p.gstin, gstin_verification_status="format_valid" if p.gstin else "unverified",
        ifsc_verification_status=check.ifsc_status,
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


FILLABLE = ("country", "gstin", "website", "contact_email")


async def fill_missing_details(db, vendor: Vendor, values: dict, filled_by: str) -> list:
    """Fills details nobody entered for an existing vendor (the risk
    scorecard's "data needed" list), with the onboarding checks. Blanks only:
    a value on record isn't changed here. Returns the errors; nothing is
    written unless there are none."""
    p = normalise(VendorProfile(name=vendor.name, **{k: values.get(k) for k in FILLABLE}))
    new = {k: getattr(p, k) for k in FILLABLE if getattr(p, k)}
    errors = [{"field": k, "message": "Already on record; change it through the vendor's review process."}
              for k in new if getattr(vendor, k, None)]
    if "country" in new:
        from shared.iso_countries import is_valid_country_code
        if not is_valid_country_code(new["country"]):
            errors.append({"field": "country", "message": f"Country '{new['country']}' must be a 2-letter ISO code."})
    if "contact_email" in new and not _EMAIL.match(new["contact_email"]):
        errors.append({"field": "contact_email", "message": "Not a valid email address."})
    if "gstin" in new:
        valid, reason = validate_gstin_offline(new["gstin"])
        if not valid:
            errors.append({"field": "gstin", "message": reason})
        elif (vendor.country or new.get("country")) != "IN":
            errors.append({"field": "gstin", "message": "A GSTIN applies to vendors registered in India (country IN)."})
        else:
            same = (await db.execute(select(Vendor).where(Vendor.gstin == new["gstin"], Vendor.id != vendor.id))).scalars().first()
            if same:
                errors.append({"field": "gstin", "message": f"Already on record for “{same.name}”."})
    if errors or not new:
        return errors or [{"field": None, "message": "Nothing to fill in."}]
    for k, v in new.items():
        setattr(vendor, k, v)
    if "gstin" in new:
        vendor.gstin_verification_status = "format_valid"
        vendor.no_gstin_confirmed_by = vendor.no_gstin_confirmed_at = None
    vendor.updated_at = datetime.now(timezone.utc)
    await write_audit_log(db, entity_type="vendor", entity_id=vendor.id, action="vendor_details_filled",
                          payload={"filled_by": filled_by, "fields": sorted(new)})
    await db.commit()
    return []
