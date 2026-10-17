"""BR-6: the vendor's risk is shown before signing, and signing for a
High-risk (or never-scored) vendor needs an explicit acknowledgement."""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

from app.services import contract_service  # noqa: E402
from app.services.contract_service import RiskAcknowledgementRequired  # noqa: E402

GSTIN_OVERRIDE = {"check": "gstin", "status": "triggered", "reason": "GSTIN is cancelled"}


def _score(band, overrides=()):
    factors = [{"feature": "on_time_delivery_rate", "contribution": 0.2}]
    if overrides:
        factors = [{"feature": "override:gstin", "override": True, "reason": "GSTIN is cancelled"}] + factors
    return SimpleNamespace(band=band, score=0.81 if band == "High" else 0.12, details=factors,
                           overrides=list(overrides) + [{"check": "sanctions", "status": "not_checked"}],
                           scored_at=datetime(2026, 10, 1, tzinfo=timezone.utc))


def _contract():
    c = MagicMock()
    c.id, c.vendor_id, c.status, c.esign_provider_ref = str(uuid.uuid4()), str(uuid.uuid4()), "pending_signature", None
    c.contract_text, c.template = "Terms", "saas_subscription"
    return c


async def _sign(score, acknowledged):
    db = AsyncMock()
    db.get.return_value = _contract()
    with patch("app.services.risk_service.latest_risk_score", new=AsyncMock(return_value=score)), \
            patch("app.services.contract_service.staged", return_value=AsyncMock()), \
            patch("app.services.contract_service.write_audit_log", new=AsyncMock()):
        return await contract_service.sign_contract_digitally(
            db, MagicMock(), "c1", signer_name="Alice", signer_email="alice@x.com",
            legal_consent=True, risk_acknowledged=acknowledged)


@pytest.mark.asyncio
async def test_high_risk_vendor_needs_an_acknowledgement():
    with pytest.raises(RiskAcknowledgementRequired, match="risk band is High"):
        await _sign(_score("High"), acknowledged=False)
    contract, cert = await _sign(_score("High"), acknowledged=True)
    assert contract.status == "signed"
    assert cert["vendor_risk_at_signing"] == {"risk_band": "High", "risk_score": 0.81, "overrides": [],
                                              "acknowledgement_required": True, "acknowledged": True}


@pytest.mark.asyncio
async def test_a_hard_override_is_named_in_the_refusal():
    with pytest.raises(RiskAcknowledgementRequired, match="GSTIN is cancelled"):
        await _sign(_score("High", [GSTIN_OVERRIDE]), acknowledged=False)


@pytest.mark.asyncio
async def test_unscored_vendor_needs_an_acknowledgement():
    with pytest.raises(RiskAcknowledgementRequired, match="not been risk-scored"):
        await _sign(None, acknowledged=False)


@pytest.mark.asyncio
async def test_low_risk_vendor_signs_without_one():
    contract, cert = await _sign(_score("Low"), acknowledged=False)
    assert contract.status == "signed"
    assert cert["vendor_risk_at_signing"]["acknowledgement_required"] is False


@pytest.mark.asyncio
async def test_signing_risk_lists_reasons_and_triggered_overrides_only():
    with patch("app.services.risk_service.latest_risk_score",
               new=AsyncMock(return_value=_score("High", [GSTIN_OVERRIDE]))):
        risk = await contract_service.signing_risk(AsyncMock(), "v1")
    assert [o["check"] for o in risk["overrides"]] == ["gstin"]
    assert [r["feature"] for r in risk["reasons"]] == ["on_time_delivery_rate"]
    assert risk["acknowledgement_reason"] == "Hard override: GSTIN is cancelled."


def test_api_answers_409_with_a_code():
    from app.api import contracts
    from app.database import get_db
    from shared.auth import get_current_user
    from shared.auth.middleware import CurrentUser
    app = FastAPI()
    app.state.kafka_producer = AsyncMock()
    app.include_router(contracts.router, prefix="/contracts")
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id="u1", email="a@x.com", role="approver")
    app.dependency_overrides[get_db] = lambda: AsyncMock()
    from shared.http.error_handlers import register_error_handlers
    register_error_handlers(app)
    refuse = AsyncMock(side_effect=RiskAcknowledgementRequired("The vendor's risk band is High. Acknowledge…"))
    with patch("app.services.contract_service.sign_contract_digitally", new=refuse), TestClient(app) as c:
        r = c.post("/contracts/c1/sign", json={"signer_name": "A", "legal_consent": True})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "risk_acknowledgement_required"
    assert refuse.await_args.kwargs["risk_acknowledged"] is False


def _generate_for(vendor_scored):
    """generate_contract_for_request for a vendor with / without a score;
    returns the score_vendor mock."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock, patch
    from app.services import clause_router, contract_service
    pr = SimpleNamespace(id="pr-1", vendor_id="v-1", department="IT", items=[], amount=1000, currency="INR",
                         requested_by="req@x")
    vendor = SimpleNamespace(id="v-1", name="Nukatir Fabugin LLC")
    db = MagicMock()
    db.get = AsyncMock(side_effect=lambda model, key: pr if key == "pr-1" else vendor)
    db.commit, db.refresh, db.rollback = AsyncMock(), AsyncMock(), AsyncMock()
    routed = clause_router.ClauseRoutingResult(
        route_name="regex_fallback", model_used="regex", fallback_triggered=True, fallback_reason="model_unavailable",
        confidence=1.0, duration_ms=1.0, clauses={"renewal_type": "auto", "notice_period_days": None, "contract_end_date": None})
    scorer = AsyncMock()
    with patch("app.services.risk_service.latest_risk_score", new=AsyncMock(return_value=object() if vendor_scored else None)), \
            patch("app.services.risk_service.score_vendor", new=scorer), \
            patch.object(clause_router, "route_clause_extraction", AsyncMock(return_value=routed)), \
            patch.object(contract_service, "write_audit_log", AsyncMock()), \
            patch.object(contract_service, "staged", return_value=None), \
            patch.object(contract_service, "start_renewal_workflow", AsyncMock()):
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(contract_service.generate_contract_for_request(db, None, "pr-1", "saas_subscription"))
        finally:
            loop.close()
    return scorer


def test_a_never_scored_vendor_is_scored_before_its_first_contract():
    """An onboarded vendor (no document, so no vendor.matched) used to reach
    signing unscored and never screened against the sanctions list."""
    assert _generate_for(vendor_scored=False).await_count == 1
    assert _generate_for(vendor_scored=True).await_count == 0
