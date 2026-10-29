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


# ── team-supplied cases (Oct 23) through the collectors ─────────────────────

def _team_vendor(name, country, email):
    return SimpleNamespace(id="v-team", name=name, country=country, contact_email=email, status="onboarding")


@pytest.mark.asyncio
@pytest.mark.parametrize("vendor,fired", [
    (_team_vendor("Caspian Petrochem Trading LLC", "IR", "export@caspian-petrochem.ir"),
     {"sanctions.status": "match", "country.prohibited": True}),
    (_team_vendor("SSPL SOLUTIONS PRIVATE LIMITED", "IN", None), {"sanctions.status": "match"}),
], ids=["caspian", "sspl"])
async def test_non_remediable_override_skips_phases_1_and_2(vendor, fired):
    """Phase 0 fast-fail: a sanctions match or prohibited country stops GST
    (Phase 1) and the external checks (Phase 2); no HTTP request is made."""
    from app.services.collectors import collector_manager as cm

    def phase0(key):
        async def fn(db, v, now, **_):
            fields = {"sanctions": {"sanctions.status": fired["sanctions.status"]},
                      "jurisdiction": {"country.prohibited": fired.get("country.prohibited", False)}}.get(key, {})
            return SimpleNamespace(signal_key=key, status="ok", fields=fields), None
        return fn

    def must_not_run(key):
        return AsyncMock(side_effect=AssertionError(f"{key} ran after a non-remediable override"))

    later = ("gst", "web", "email", "breach", "certification", "financial", "adverse_media")
    patches = [patch.object(cm, f"collect_{k}", phase0(k)) for k in
               ("sanctions", "jurisdiction", "bank", "company_age", "delivery_sla", "feedback", "incidents")]
    patches += [patch.object(cm, f"collect_{k}", must_not_run(k)) for k in later]
    skipped = AsyncMock(side_effect=lambda **kw: SimpleNamespace(signal_key=kw["signal_key"], status="not_checked",
                                                                 skip_reason=kw["skip_reason"]))
    patches += [patch.object(cm, "_record_skipped_signal", skipped),
                patch("httpx.AsyncClient", side_effect=AssertionError("external HTTP call")),
                patch("httpx.Client", side_effect=AssertionError("external HTTP call"))]
    for p in patches:
        p.start()
    try:
        obs = await cm.collect_all_signals(MagicMock(), vendor, now=rt.NOW)
    finally:
        for p in patches:
            p.stop()
    assert {k for k, o in obs.items() if o.status == "not_checked"} == set(later)
    assert {o.skip_reason for k, o in obs.items() if k in later} == {"skipped_nonremediable_override"}


@pytest.mark.asyncio
async def test_unchecked_breach_history_is_not_reported_as_clean():
    """ADDA (adda.io, legal name 3Five8 Technologies): a breach was reported.
    With no live lookup the collector must say "not checked", never "no
    breach listed", until the record and the entity match are verified."""
    from app.services.collectors import cyber_collectors as cc
    from app.services.scorecard.default_ruleset import get_default_ruleset
    from app.services.scorecard.engine import evaluate_risk
    recorded = {}

    async def observation(**kw):
        recorded.update(kw)
        return SimpleNamespace(**kw)

    vendor = _team_vendor("3Five8 Technologies Pvt. Ltd.", "IN", "support@adda.io")
    db = AsyncMock()
    no_catalogue = AsyncMock(return_value={"catalogue_loaded": False, "not_assessed_reason": "catalogue not loaded"})
    with patch.object(cc, "record_raw_response", AsyncMock(return_value=SimpleNamespace(id="raw"))), \
            patch.object(cc, "record_observation", observation), \
            patch.object(cc, "match_vendor_breaches", no_catalogue):
        obs, _ = await cc.collect_breach(db, vendor, rt.NOW)
    assert recorded["fields"]["breach.domain"] == "adda.io"
    assert recorded["status"] == "not_checked"
    result = evaluate_risk(get_default_ruleset(), {"breach": obs}, rt.NOW,
                           vendor_context={"name": vendor.name, "inherent_tier": "critical", "country": "IN"})
    breach = next(r for r in result["rule_results"] if r["signal_key"] == "breach")
    assert breach["status"] == "not_assessed" and breach["points"] == 0


def _not_json():
    raise ValueError("plain text")


async def _media(monkeypatch, api_key, responses, name="Infosys Limited"):
    """Runs collect_adverse_media in live mode; `responses` answer the HTTP
    calls in order (GDELT first, then the Guardian when a key is set)."""
    from app.services.collectors import reputation_collectors as rc
    from app.services.scorecard.default_ruleset import get_default_ruleset
    from app.services.scorecard.engine import evaluate_risk
    monkeypatch.setenv("GUARDIAN_API_KEY", api_key)
    monkeypatch.setattr(rc, "GDELT_MIN_INTERVAL_S", 0)
    recorded = {}

    async def observation(**kw):
        recorded.update(kw)
        return SimpleNamespace(**kw)

    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(side_effect=responses)
    breaker = MagicMock(can_execute=AsyncMock(return_value=True), record_success=AsyncMock(),
                        record_failure=AsyncMock())
    db = AsyncMock()
    db.execute.return_value = MagicMock(all=MagicMock(return_value=[]))
    with patch("shared.live_mode.checker.is_live_verification_enabled", AsyncMock(return_value=True)), \
            patch.object(rc.httpx, "AsyncClient", return_value=client), \
            patch.object(rc, "CircuitBreaker", return_value=breaker), \
            patch.object(rc, "record_raw_response", AsyncMock(return_value=SimpleNamespace(id="raw"))), \
            patch.object(rc, "record_observation", observation):
        obs, _ = await rc.collect_adverse_media(db, _team_vendor(name, "IN", None), rt.NOW,
                                                lexicon=get_default_ruleset()["lookups"]["adverse_media_lexicon"])
    result = evaluate_risk(get_default_ruleset(), {"adverse_media": obs}, rt.NOW,
                           vendor_context={"name": name, "country": "IN"})
    return recorded["fields"], next(r for r in result["rule_results"] if r["signal_key"] == "adverse_media")


@pytest.mark.asyncio
@pytest.mark.parametrize("api_key,http_status", [("", 429), ("bad-key", 401), ("good-key", 429), ("good-key", 503)])
async def test_refused_news_search_is_not_reported_as_no_adverse_media(api_key, http_status, monkeypatch):
    """A keyless or rejected call answers with an error, not results. That
    must read "not assessed", never "no adverse media found"."""
    refused = SimpleNamespace(status_code=http_status, json=lambda: {})
    fields, media = await _media(monkeypatch, api_key, [refused, refused])
    assert fields["media.sources_reachable"] is False
    assert media["status"] == "not_assessed"


@pytest.mark.asyncio
async def test_gdelt_rate_limit_text_is_not_a_search(monkeypatch):
    """GDELT answers a too-fast call with HTTP 200 and a plain-text notice."""
    fields, media = await _media(monkeypatch, "", [SimpleNamespace(status_code=200, json=_not_json)])
    assert fields["media.sources_reachable"] is False and media["status"] == "not_assessed"


@pytest.mark.asyncio
async def test_news_naming_the_brand_counts_for_the_legal_entity(monkeypatch):
    """Headlines say "Hathway", not "Hathway Cable and Datacom Limited"; the
    ruleset's lexicon (with its data-breach category) is the one applied."""
    articles = {"articles": [
        {"title": "Hathway hit by data breach, 4 million customers exposed", "url": "https://x/1",
         "seendate": "20261001T000000Z", "domain": "example.in"},
        {"title": "Hathway launches new broadband plans", "url": "https://x/2",
         "seendate": "20261002T000000Z", "domain": "example.in"},
        {"title": "Unrelated company fined for fraud", "url": "https://x/3",
         "seendate": "20261003T000000Z", "domain": "example.in"}]}
    fields, media = await _media(monkeypatch, "", [SimpleNamespace(status_code=200, json=lambda: articles)],
                                 name="Hathway Cable and Datacom Limited")
    assert fields["media.sources_reachable"] is True
    assert fields["media.qualifying_articles"] == 1
    assert media["status"] == "assessed" and media["points"] == 1


@pytest.mark.asyncio
async def test_what_if_with_no_changes_reproduces_the_stored_score():
    """The stored snapshot is {signal: fields}. Fed to the engine unconverted,
    every signal read as empty and the what-if showed "not rated" for a rated
    vendor; the remediation plan started from the same empty state."""
    from app.api import vendors as api
    from app.services.scorecard.default_ruleset import get_default_ruleset
    from app.services.scorecard.engine import evaluate_risk
    ruleset = get_default_ruleset()
    observations = {k: {"signal_key": k, "status": "ok", "fields": f, "fetched_at": rt.NOW.isoformat()}
                    for k, f in rt.obs(feedback={"fbk.count_12m": 8, "fbk.mean_12m": 2.5}).items()}
    context = {"name": "Acme", "spend_tier": "standard", "inherent_tier": "moderate", "country": "IN"}
    stored = evaluate_risk(ruleset, observations, rt.NOW, vendor_context=context)
    assert stored["rating_status"] == "assessed" and stored["total_points"] == 8
    score = SimpleNamespace(snapshot=stored["snapshot"])
    vendor = SimpleNamespace(name="Acme", vendor_tier="standard", inherent_tier="moderate", country="IN")
    db = AsyncMock()
    db.get.return_value = vendor
    with patch.object(api.risk_service, "latest_risk_score", AsyncMock(return_value=score)), \
            patch.object(api.risk_service, "get_active_ruleset", AsyncMock(return_value=SimpleNamespace(definition=ruleset))):
        same = (await api.what_if_simulation("v1", api.WhatIfBody(hypothetical_fields={}), db=db, user=None)).data
        worse = (await api.what_if_simulation("v1", api.WhatIfBody(hypothetical_fields={"fin.rating_class": "non_investment"}),
                                              db=db, user=None)).data
    assert (same["total_points"], same["final_band"], same["rating_status"]) == (8, "Low", "assessed")
    assert (worse["total_points"], worse["final_band"]) == (10, "Low")
