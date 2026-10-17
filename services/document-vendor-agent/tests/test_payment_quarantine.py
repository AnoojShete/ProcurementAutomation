"""First-seen bank details, lookalike vendors, payment holds."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rapidfuzz import fuzz

from app.api.showcase import lookalike_name
from app.services import pipeline
from app.services.vendor_matching import VendorMatchResult, normalize_vendor_name


def _vendor(name, bank=None, pending=False):
    return SimpleNamespace(
        id=f"id-{name}", name=name, normalized_name=normalize_vendor_name(name),
        bank_account_number=bank, routing_code=None, payment_beneficiary_name=None,
        payment_details_pending_verification=pending,
    )


def _envelope(doc_type="invoice", bank="123456789012"):
    fields = {"vendor_name_raw": "De1l Technologies"}
    if bank:
        fields.update(bank_account_number=bank, routing_code="HDFC0001234", payment_beneficiary_name="De1l Technologies")
    return {"document_id": "doc-1", "document_type": doc_type, "extracted_fields": fields, "_agent_trail": []}


async def _run(match, env, submit_result="change"):
    submit = AsyncMock(return_value=submit_result)

    def flag_pending(*a, **k):
        match.vendor.payment_details_pending_verification = True
        return submit_result

    submit.side_effect = flag_pending
    with patch.object(pipeline, "find_or_create_vendor", AsyncMock(return_value=match)), \
         patch.object(pipeline, "submit_payment_change", submit), \
         patch.object(pipeline, "write_audit_log", AsyncMock()) as audit:
        out = await pipeline.vendor_matching_agent(AsyncMock(), AsyncMock(), env, "uploader@acme.test")
    return out, submit, audit


@pytest.mark.asyncio
async def test_first_seen_bank_details_go_to_verification_not_onto_the_vendor():
    new = _vendor("Brand New Vendor")
    match = VendorMatchResult(vendor=new, match_type="new", match_confidence=1.0)
    env, submit, _ = await _run(match, _envelope())

    assert submit.call_args.kwargs["source"] == "document_first_seen"
    assert new.bank_account_number is None  # not trusted on first sight
    assert env["payment_hold"] is True
    assert "awaiting verification" in env["payment_hold_reason"]


@pytest.mark.asyncio
async def test_lookalike_vendor_is_flagged_and_held():
    real = _vendor("Dell Technologies", bank="999900001111")
    fake = _vendor("De1l Technologies")
    match = VendorMatchResult(vendor=fake, match_type="new", match_confidence=1.0,
                              closest_existing=real, closest_score=82.0)
    env, _, audit = await _run(match, _envelope())

    assert env["lookalike_vendor"]["vendor_name"] == "Dell Technologies"
    assert env["lookalike_vendor"]["bank_details_differ"] is True
    assert env["needs_review_forced"] is True
    assert "resembles existing vendor" in env["payment_hold_reason"]
    assert audit.call_args.kwargs["action"] == "lookalike_vendor_detected"


@pytest.mark.asyncio
async def test_distant_new_vendor_is_not_a_lookalike():
    match = VendorMatchResult(vendor=_vendor("Acme Widgets"), match_type="new", match_confidence=1.0,
                              closest_existing=_vendor("Dell Technologies"), closest_score=30.0)
    env, _, _ = await _run(match, _envelope(bank=None), submit_result=None)
    assert "lookalike_vendor" not in env
    assert env["payment_hold"] is False


@pytest.mark.asyncio
async def test_quotes_are_never_held():
    match = VendorMatchResult(vendor=_vendor("Brand New Vendor"), match_type="new", match_confidence=1.0)
    with patch("app.models.VendorQuote", MagicMock()):
        env, submit, _ = await _run(match, _envelope(doc_type="quote"))
    submit.assert_not_called()
    assert env["payment_hold"] is False


@pytest.mark.parametrize("name", ["Dell Technologies India Pvt Ltd", "Freshworks Inc", "Atlassian Pty Ltd",
                                  "Zoho Corporation", "HP India Sales Pvt Ltd"])
def test_showcase_lookalike_lands_in_the_flag_band(name):
    fake = lookalike_name(name)
    assert fake and fake != name
    score = fuzz.token_sort_ratio(normalize_vendor_name(name), normalize_vendor_name(fake))
    assert 70 <= score < 88
