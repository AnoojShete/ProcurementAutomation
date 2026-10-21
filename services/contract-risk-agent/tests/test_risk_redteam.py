"""FR-04: the red-team set (ml/redteam_scorecard.py) through the real
scorecard engine and clearance gate, and the API-level controls behind the
four findings it led to:

  1. an admin's "accept risk" cleared a sanctioned vendor (non-remediable
     override) — now refused when recorded and ignored by the gate;
  2. an old approval kept a vendor cleared after its score turned High;
  3. the petty exception cleared a vendor whose possible sanctions match was
     awaiting review;
  4. a vendor with no country of incorporation was rated assessed Low.
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ml"))
import redteam_scorecard as rt  # noqa: E402

from app.services import clearance  # noqa: E402


@pytest.mark.parametrize("profile", rt.PROFILES, ids=[p["name"] for p in rt.PROFILES])
def test_red_team_profile(profile):
    result = rt.run_profile(profile)
    assert result["passed"], result["problems"]


def test_red_team_covers_every_hard_override_and_gate_reason():
    """The set must exercise each override the Agent doc lists and each way
    the gate can refuse."""
    results = rt.run_all()
    overrides = {o for r in results for o in r["got"]["overrides"]}
    assert {"R-SAN-01", "R-GST-01", "R-JUR-01"} <= overrides
    reasons = {x.split("_until_")[0] for r in results for x in r["got"]["reasons"]}
    assert {"vendor_not_rated", "rating_provisional", "high_risk_band", "decision_rejected", "approval_ineligible",
            "condition_overdue", "cleared_under_petty_exception", "risk_accepted"} <= reasons


def test_missing_data_is_never_shown_as_low():
    for r in rt.run_all():
        if r["got"]["rating_status"] != "assessed":
            assert r["got"]["final_band"] in ("Unrated", "Medium", "High"), r["name"]


def test_the_engine_is_deterministic():
    p = rt.PROFILES[14]
    assert rt.run_profile(p)["got"] == rt.run_profile(p)["got"]


# ── finding 1 at the API: accept_risk refused for a non-remediable override ──

def _client(role="admin", overrides=("R-SAN-01",), non_remediable=("R-SAN-01",)):
    from app.api import vendors
    from app.database import get_db
    from shared.auth import get_current_user
    from shared.auth.middleware import CurrentUser
    app = FastAPI()
    app.include_router(vendors.router, prefix="/vendors")
    db = AsyncMock()
    db.get.return_value = SimpleNamespace(id="v1", name="Rosoboron", status="active", vendor_tier="standard")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id="u", email=f"{role}@x.test", role=role)
    score = SimpleNamespace(id="s1", rating_status="assessed", final_band="High", band="High", is_provisional=False)
    view = clearance.ScoreView("assessed", "High", override_rule_ids=list(overrides), non_remediable=set(non_remediable))
    return TestClient(app), db, score, view


def test_accept_risk_on_a_sanctions_match_is_refused():
    c, db, score, view = _client()
    with patch("app.services.risk_service.latest_risk_score", AsyncMock(return_value=score)), \
            patch("app.services.clearance.load", AsyncMock(return_value=(db.get.return_value, view, None))):
        r = c.post("/vendors/v1/decisions", json={"decision": "accept_risk",
                                                  "justification": "Business critical, accepting for now"})
    assert r.status_code == 400 and "non_remediable_override" in r.text
    db.add.assert_not_called()


def test_accept_risk_on_a_remediable_override_is_recorded():
    c, db, score, view = _client(overrides=("R-GST-01",), non_remediable=())
    db.refresh = AsyncMock()
    with patch("app.services.risk_service.latest_risk_score", AsyncMock(return_value=score)), \
            patch("app.services.clearance.load", AsyncMock(return_value=(db.get.return_value, view, None))), \
            patch("app.services.audit.write_audit_log", AsyncMock()):
        r = c.post("/vendors/v1/decisions", json={"decision": "accept_risk", "expires_in_days": 10,
                                                  "justification": "GSTIN reactivation filed, ack no. 123"})
    assert r.status_code == 200, r.text
    assert db.add.call_args.args[0].decided_by == "admin@x.test"          # from the token


def test_procurement_role_no_longer_records_decisions():
    c, *_ = _client(role="procurement")
    r = c.post("/vendors/v1/decisions", json={"decision": "reject", "justification": "no"})
    assert r.status_code == 403


# ── the same decision for /clearance and signing (G1) ───────────────────────

@pytest.mark.asyncio
async def test_clearance_and_signing_agree():
    from app.services import contract_service
    now = datetime.now(timezone.utc)
    vendor = SimpleNamespace(status="active", vendor_tier="standard")
    row = SimpleNamespace(id="s1", final_band="Unrated", band="Unrated", rating_status="provisional",
                          score=None, details=[], override_rule_ids=[], scored_at=None)
    for decision in (None, clearance.DecisionView("accept_risk", now + timedelta(days=5), [])):
        loaded = AsyncMock(return_value=(vendor, clearance.score_view(row, set()), decision))
        with patch("app.services.clearance.load", loaded), \
                patch("app.services.risk_service.latest_risk_score", AsyncMock(return_value=row)):
            gate = await clearance.evaluate(MagicMock(), "v1", purpose="contract")
            sign = await contract_service.signing_risk(MagicMock(), "v1")
        assert gate["cleared"] is (not sign["acknowledgement_required"])
        assert gate["reasons"] == sign["clearance_reasons"]


# ── G10: the ruleset against the synthetic incident data ────────────────────

def test_scorecard_ranks_incidents_at_least_as_well_as_the_retired_model():
    import evaluate_scorecard as ev
    result = ev.evaluate()
    assert result["roc_auc_scorecard_points"] >= ev.RF_ROC_AUC
    assert result["roc_auc_scorecard_points"] <= result["roc_auc_ceiling_label_rule"] + 0.01
    low, medium = result["bands"][0], result["bands"][1]
    assert medium["incident_rate"] > 2 * low["incident_rate"]


# ── finding 5: nobody signs with a sanctioned vendor, acknowledged or not ──

@pytest.mark.asyncio
async def test_sanctioned_vendor_cannot_be_signed_even_with_acknowledgement():
    from app.services import contract_service
    vendor = SimpleNamespace(status="active", vendor_tier="standard")
    row = SimpleNamespace(id="s1", final_band="High", band="High", rating_status="assessed", score=0.1, details=[],
                          override_rule_ids=["R-SAN-01"], scored_at=None)
    view = clearance.score_view(row, {"R-SAN-01"})
    contract = MagicMock(id="c1", vendor_id="v1", status="pending_signature", esign_provider_ref=None,
                         purchase_request_id=None)
    db = AsyncMock()
    db.get.return_value = contract
    with patch("app.services.clearance.load", AsyncMock(return_value=(vendor, view, None))), \
            patch("app.services.risk_service.latest_risk_score", AsyncMock(return_value=row)):
        risk = await contract_service.signing_risk(db, "v1")
        assert risk["signing_blocked"] and "R-SAN-01" in risk["blocked_reason"]
        with pytest.raises(contract_service.VendorBlocked):
            await contract_service.sign_contract_digitally(db, MagicMock(), "c1", signer_name="F", signer_email="f@x",
                                                           legal_consent=True, risk_acknowledged=True)
    assert contract.status == "pending_signature"


@pytest.mark.asyncio
async def test_remediable_override_can_still_be_signed_with_acknowledgement():
    from app.services import contract_service
    vendor = SimpleNamespace(status="active", vendor_tier="standard")
    row = SimpleNamespace(id="s1", final_band="High", band="High", rating_status="assessed", score=0.2, details=[],
                          override_rule_ids=["R-GST-01"], scored_at=None)
    with patch("app.services.clearance.load", AsyncMock(return_value=(vendor, clearance.score_view(row, set()), None))), \
            patch("app.services.risk_service.latest_risk_score", AsyncMock(return_value=row)):
        risk = await contract_service.signing_risk(AsyncMock(), "v1")
    assert risk["acknowledgement_required"] and not risk["signing_blocked"]
