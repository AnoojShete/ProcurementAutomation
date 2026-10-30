"""BR-4: vendor onboarding validates the profile (fields, duplicates,
look-alikes, GSTIN, IFSC), asks for confirmation of warnings, and sends
bank details to two-person verification instead of making them live."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import vendor_onboarding as vo
from app.services.vendor_onboarding import VendorProfile

GOOD_GSTIN = "27AAPFU0939F1ZV"   # valid format + check digit


def _profile(**kw):
    base = dict(name="Acme Cloud Pvt Ltd", country="IN", contact_email="ops@acme.example", contact_phone="+91 98765 43210",
                gstin=GOOD_GSTIN, bank_account_number="000123456789", routing_code="HDFC0001234")
    return VendorProfile(**{**base, **kw})


def _db(existing=()):
    db = AsyncMock()
    db.add = MagicMock()
    res = MagicMock()
    res.scalars.return_value.all.return_value = list(existing)
    db.execute.return_value = res
    return db


def _vendor(name, gstin=None):
    return SimpleNamespace(id="v-" + name[:3], name=name, normalized_name=None, gstin=gstin)


def run(c):
    return asyncio.run(c)


def test_good_profile_passes_field_checks():
    assert vo.check_fields(vo.normalise(_profile())).ok


@pytest.mark.parametrize("field,value,message", [
    ("name", " ", "Vendor name is required"),
    ("contact_email", "not-an-email", "valid email"),
    ("gstin", "27AAPFU0939F1ZX", "check-digit"),
    ("routing_code", "HDFC1234", "IFSC must look like"),
    ("bank_account_number", "12-34", "9–18 digits"),
])
def test_bad_fields_are_errors(field, value, message):
    check = vo.check_fields(vo.normalise(_profile(**{field: value})))
    assert not check.ok and any(message in e["message"] for e in check.errors), check.errors


def test_half_a_bank_detail_is_an_error():
    check = vo.check_fields(vo.normalise(_profile(routing_code=None)))
    assert any("both the account number and the IFSC" in e["message"] for e in check.errors)


def test_duplicate_gstin_and_duplicate_name_are_blocked():
    by_gstin = run(vo.validate_profile(_db([_vendor("Totally Different Ltd", GOOD_GSTIN)]), _profile()))
    assert any("same GSTIN" in e["message"] for e in by_gstin.errors)
    by_name = run(vo.validate_profile(_db([_vendor("ACME CLOUD PVT LTD")]), _profile(gstin=None)))
    assert any("Duplicate of existing vendor" in e["message"] for e in by_name.errors)


def test_lookalike_and_no_gstin_need_confirmation():
    check = run(vo.validate_profile(_db([_vendor("Acme Cloud Systems")]), _profile(gstin=None)))
    assert check.ok
    assert vo.required_confirmations(check) == {"lookalike", "no_gstin"}


def test_unknown_ifsc_is_an_error():
    ifsc = AsyncMock(return_value=SimpleNamespace(status="invalid"))
    check = run(vo.validate_profile(_db(), _profile(), check_ifsc=ifsc))
    assert any("does not exist" in e["message"] for e in check.errors)


def test_onboarding_waits_for_confirmations(monkeypatch):
    vendor, check, missing = run(vo.onboard_vendor(_db(), None, _profile(gstin=None), "fin@x", set(), None))
    assert vendor is None and missing == {"no_gstin"}
    # confirming without a reason still isn't enough
    _, _, missing = run(vo.onboard_vendor(_db(), None, _profile(gstin=None), "fin@x", {"no_gstin"}, " "))
    assert missing == {"no_gstin"}


def test_bank_details_go_to_two_person_verification(monkeypatch):
    submit = AsyncMock()
    monkeypatch.setattr("app.services.vendor_payment_service.submit_payment_change", submit)
    monkeypatch.setattr(vo, "write_audit_log", AsyncMock())
    db = _db()
    vendor, check, missing = run(vo.onboard_vendor(db, None, _profile(), "fin@x", set(), None))
    assert vendor is not None and not missing
    assert vendor.bank_account_number is None          # not live
    kwargs = submit.await_args.kwargs
    assert kwargs["new_bank_account"] == "000123456789" and kwargs["source"] == "onboarding"
    assert kwargs["submitted_by"] == "fin@x"
    db.commit.assert_awaited()


def test_onboarded_vendor_has_status_onboarding(monkeypatch):
    monkeypatch.setattr("app.services.vendor_payment_service.submit_payment_change", AsyncMock())
    monkeypatch.setattr(vo, "write_audit_log", AsyncMock())
    db = _db()
    vendor, check, missing = run(vo.onboard_vendor(
        db, None,
        _profile(inherent_tier="critical", swift_bic="CHASUS33XXX", bank_name="JPMorgan", website="https://acme.com"),
        "fin@x", set(), None
    ))
    assert vendor is not None
    assert vendor.status == "onboarding"
    assert vendor.inherent_tier == "critical"
    assert vendor.swift_bic == "CHASUS33XXX"
    assert vendor.bank_name == "JPMorgan"
    assert vendor.website == "https://acme.com"


def test_foreign_vendor_with_swift_bic():
    # Valid foreign SWIFT passes without IFSC
    check_valid = vo.check_fields(vo.normalise(_profile(
        country="US", gstin=None, routing_code=None, swift_bic="CHASUS33XXX", bank_account_number="1234567890"
    )))
    assert check_valid.ok

    # Malformed SWIFT is rejected
    check_bad_swift = vo.check_fields(vo.normalise(_profile(
        country="US", gstin=None, routing_code=None, swift_bic="SHORT", bank_account_number="1234567890"
    )))
    assert not check_bad_swift.ok
    assert any("SWIFT/BIC must be a valid" in e["message"] for e in check_bad_swift.errors)


def _blank_vendor(**kw):
    base = dict(id="v-dell", name="Dell Technologies India Pvt Ltd", country=None, gstin=None, website=None,
                contact_email=None, no_gstin_confirmed_by=None, no_gstin_confirmed_at=None)
    return SimpleNamespace(**{**base, **kw})


def _db_gstin_owner(owner=None):
    db = AsyncMock()
    res = MagicMock()
    res.scalars.return_value.first.return_value = owner
    db.execute.return_value = res
    return db


def test_missing_details_are_filled_with_the_onboarding_checks(monkeypatch):
    """The risk scorecard's "data needed" items can be filled in later."""
    monkeypatch.setattr(vo, "write_audit_log", AsyncMock())
    v = _blank_vendor(no_gstin_confirmed_by="old@x")
    assert run(vo.fill_missing_details(_db_gstin_owner(), v, {"country": "in", "gstin": GOOD_GSTIN.lower(),
                                                              "contact_email": "Ops@Dell.example"}, "fin@x")) == []
    assert (v.country, v.gstin, v.contact_email) == ("IN", GOOD_GSTIN, "ops@dell.example")
    assert v.gstin_verification_status == "format_valid" and v.no_gstin_confirmed_by is None


@pytest.mark.parametrize("vendor_kw, values, message", [
    ({"country": "IN"}, {"country": "US"}, "Already on record"),       # blanks only
    ({}, {"country": "XX"}, "2-letter ISO code"),
    ({"country": "IN"}, {"gstin": "27AAPFU0939F1ZX"}, ""),              # bad check digit
    ({"country": "US"}, {"gstin": GOOD_GSTIN}, "registered in India"),
    ({}, {"contact_email": "not-an-email"}, "valid email"),
    ({}, {}, "Nothing to fill in"),
])
def test_bad_or_existing_details_are_refused(monkeypatch, vendor_kw, values, message):
    monkeypatch.setattr(vo, "write_audit_log", AsyncMock())
    v = _blank_vendor(**vendor_kw)
    before = dict(vars(v))
    errors = run(vo.fill_missing_details(_db_gstin_owner(), v, values, "fin@x"))
    assert errors and message in errors[0]["message"]
    assert vars(v) == before


def test_a_gstin_already_on_another_vendor_is_refused(monkeypatch):
    monkeypatch.setattr(vo, "write_audit_log", AsyncMock())
    v = _blank_vendor(country="IN")
    errors = run(vo.fill_missing_details(_db_gstin_owner(SimpleNamespace(name="Other Ltd")), v,
                                         {"gstin": GOOD_GSTIN}, "fin@x"))
    assert errors and "Other Ltd" in errors[0]["message"] and v.gstin is None
