"""Tests for Prompt 9C Amendments:
- New 100-point allocation and Ruleset validator checks
- Brand-new vendor rating_status = 'not_rated', score = None, final_band = 'Unrated'
- Foreign vendors: GST R-GST-04 not_applicable, bank R-BNK-04 not_applicable
- Petty exception: purchase <= 50,000 INR for low-tier provisional vendor
- Purpose-based clearance and activation deadlock prevention (User Correction 2)
- Circuit breaker state machine (Section E2)
- Adverse media lexicon-based extraction (Section F2)
- Cumulative remediation path, override-clearing priority, fixed wording templates (Section G, User Correction 3)
- User Correction 1: clean detect_only signals excluded from applicable_dd_max
"""
import copy
import os
import sys
import time
import pytest
from datetime import datetime, timezone

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("APP_ESIGN_WEBHOOK_SECRET", "test-secret")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

from app.services.scorecard.default_ruleset import get_default_ruleset
from app.services.scorecard.ruleset_v2 import RULESET_V2_DEFINITION as RULESET_V2
from app.services.scorecard.validator import validate_ruleset, RulesetValidationError
from app.services.scorecard.engine import evaluate_risk
from app.services.scorecard.remediation import build_remediation_plan, simulate_what_if
from app.services.collectors.circuit_breaker import CircuitBreaker


# =====================================================================
# 1. VALIDATOR TESTS (Section A & Publish Validation)
# =====================================================================
def test_ruleset_validator_sum_100():
    valid, errs = validate_ruleset(RULESET_V2)
    assert valid is True, f"RULESET_V2 failed validation: {errs}"

    # Mutate max_points sum != 100
    invalid_rs = copy.deepcopy(RULESET_V2)
    invalid_rs["signals"][0]["max_points"] = 50
    valid, errs = validate_ruleset(invalid_rs)
    assert valid is False
    assert any("sum" in e.get("message", "").lower() for e in errs)


def test_ruleset_validator_detect_only_constraints():
    # Detect only with potential points
    invalid_rs = copy.deepcopy(RULESET_V2)
    for s in invalid_rs["signals"]:
        if s["key"] == "breach":
            # R-BRC-08 (review_pending) may carry potential points; a scored outcome may not.
            next(o for o in s["outcomes"] if o["status"] == "assessed")["potential_points"] = 4
    valid, errs = validate_ruleset(invalid_rs)
    assert valid is False
    assert any("potential_points" in e.get("message", "") for e in errs)

    # Detect only in required_signals
    invalid_rs2 = copy.deepcopy(RULESET_V2)
    invalid_rs2["required_signals_by_tier"]["low"] = ["breach"]
    valid2, errs2 = validate_ruleset(invalid_rs2)
    assert valid2 is False
    assert any("detect_only signal 'breach' may not appear" in e.get("message", "") for e in errs2)


def test_ruleset_validator_short_circuit_external():
    # short_circuit_external on outcome without override_band
    invalid_rs = copy.deepcopy(RULESET_V2)
    for s in invalid_rs["signals"]:
        if s["key"] == "bank":
            s["outcomes"][0]["short_circuit_external"] = True
            s["outcomes"][0].pop("override_band", None)
    valid, errs = validate_ruleset(invalid_rs)
    assert valid is False
    assert any("short_circuit_external" in e.get("message", "") for e in errs)


# =====================================================================
# 2. BRAND-NEW VENDOR (Section C2, D3)
# =====================================================================
def test_brand_new_vendor_unrated():
    now = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)
    # Empty observations dict
    res = evaluate_risk(RULESET_V2, {}, now)

    assert res["rating_status"] == "not_rated"
    assert res["final_band"] == "Unrated"
    assert res["risk_score"] is None
    assert res["assessed_share_pct"] == 0
    assert res["points_is_lower_bound"] is False


# =====================================================================
# 3. USER CORRECTION 1: 100% CLEAN VENDOR REACHES 100% ASSESSED SHARE
# =====================================================================
def test_clean_vendor_reaches_100_percent_assessed():
    now = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)
    # Fully assessed clean domestic vendor
    obs = {
        "sanctions": {"fields": {"sanctions.status": "no_match"}},
        "gst": {"fields": {"gstin.status": "active", "gstin.verification_level": "live", "gstin.name_match_level": "exact"}},
        "bank": {"fields": {"bank.status": "valid", "bank.change_pending": False}},
        "jurisdiction": {"fields": {"country.is_domestic": True, "country.prohibited": False, "country.high_risk": False}},
        "delivery_sla": {"fields": {"sla.orders_delivered": 10, "sla.on_time_pct": 95}},
        "feedback": {"fields": {"fb.ratings_count_12m": 5, "fb.mean_12m": 4.5}},
        "incidents": {"fields": {"inc.history_available": True, "inc.count_24m": 0}},
        "web": {"fields": {"web.reachable": True, "web.ssl_grade": "A", "web.cert_valid": True}},
        "email": {"fields": {"email.dmarc_policy": "reject", "email.spf_present": True}},
        "breach": {"fields": {"breach.source_reachable": True, "breach.catalogue_loaded": True, "breach.count_5y": 0, "breach.domain": "acme.com"}},
        "certification": {"fields": {"cert.required": True, "cert.status": "valid"}},
        "financial": {"fields": {"fin.basis": "rating", "fin.rating_class": "investment", "fin.evidence_age_days": 30}},
        "company_age": {"fields": {"age.years": 5.0, "age.basis": "incorporation"}},
        "adverse_media": {"fields": {"media.sources_reachable": True, "media.qualifying_articles": 0}},
    }

    res = evaluate_risk(RULESET_V2, obs, now, vendor_context={"spend_tier": "critical", "country": "IN"})

    assert res["rating_status"] == "assessed"
    assert res["total_points"] == 0
    assert res["final_band"] == "Low"
    assert res["points_is_lower_bound"] is False
    assert res["assessed_share_pct"] == 100, f"Expected 100% assessed_share_pct, got {res['assessed_share_pct']}"


# =====================================================================
# 4. FOREIGN VENDORS AND GST (Section B)
# =====================================================================
def test_foreign_vendor_gst_and_bank():
    now = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)
    obs = {
        # foreign gstin
        "gst": {"fields": {"gstin.verification_level": "foreign", "gstin.number": "None"}},
        # foreign bank
        "bank": {"fields": {"bank.status": "foreign_account"}},
        "sanctions": {"fields": {"sanctions.status": "no_match"}},
        "jurisdiction": {"fields": {"country.is_domestic": False, "country.prohibited": False, "country.high_risk": False, "country.wgi_composite": 0.5}},
    }

    res = evaluate_risk(RULESET_V2, obs, now)
    rule_results_by_signal = {r["signal_key"]: r for r in res["rule_results"]}

    # GST fires R-GST-04 (not_applicable, 0 pts, 0 potential)
    gst_res = rule_results_by_signal["gst"]
    assert gst_res["rule_id"] == "R-GST-04"
    assert gst_res["status"] == "not_applicable"
    assert gst_res["points"] == 0
    assert gst_res["potential_points"] == 0

    # Bank fires R-BNK-04 (not_applicable, 0 pts, 0 potential)
    bnk_res = rule_results_by_signal["bank"]
    assert bnk_res["rule_id"] == "R-BNK-04"
    assert bnk_res["status"] == "not_applicable"
    assert bnk_res["points"] == 0
    assert bnk_res["potential_points"] == 0

    # Foreign vendor is not blocked on GST or Bank
    assert "gstin_cancelled" not in res["blocked_by"]
    assert "bank_invalid" not in res["blocked_by"]


# =====================================================================
# 5. REMEDIATION PLAN & CUMULATIVE PATH (Section G)
# =====================================================================
def test_remediation_cumulative_override_priority():
    now = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)
    # Vendor with cancelled GSTIN override (points 20, OV High) and invalid bank (5 pts)
    obs = {
        "gst": {"fields": {"gstin.status": "cancelled", "gstin.verification_level": "live"}},
        "bank": {"fields": {"bank.status": "invalid", "bank.change_pending": False}},
        "sanctions": {"fields": {"sanctions.status": "no_match"}},
        "jurisdiction": {"fields": {"country.is_domestic": True, "country.prohibited": False, "country.high_risk": False}},
        "web": {"fields": {"web.reachable": True, "web.ssl_grade": "A", "web.cert_valid": True}},
        "email": {"fields": {"email.dmarc_policy": "reject", "email.spf_present": True}},
        "breach": {"fields": {"breach.source_reachable": True, "breach.catalogue_loaded": True, "breach.count_5y": 0}},
        "certification": {"fields": {"cert.required": True, "cert.status": "valid"}},
        "financial": {"fields": {"fin.basis": "rating", "fin.rating_class": "investment"}},
        "company_age": {"fields": {"age.years": 5.0, "age.basis": "incorporation"}},
        "adverse_media": {"fields": {"media.sources_reachable": True, "media.qualifying_articles": 0}},
        "delivery_sla": {"fields": {"sla.orders_delivered": 10, "sla.on_time_pct": 95}},
        "feedback": {"fields": {"fb.ratings_count_12m": 5, "fb.mean_12m": 4.5}},
        "incidents": {"fields": {"inc.history_available": True, "inc.count_24m": 0}},
    }

    domestic = {"spend_tier": "standard", "country": "IN"}
    eval_res = evaluate_risk(RULESET_V2, obs, now, vendor_context=domestic)
    assert eval_res["final_band"] == "High"
    assert "R-GST-01" in [b["rule_id"] for b in eval_res["blocked_by"]]

    plan = build_remediation_plan(RULESET_V2, eval_res, obs, now, vendor_context=domestic)
    steps = plan["steps"]

    # Step 1 MUST be clearing the GST override
    assert len(steps) >= 2
    step1 = steps[0]
    assert step1["signal_key"] == "gst"
    assert step1["remediable"] is True
    assert "Provide evidence of GSTIN reactivation" in step1["action"]
    assert step1["band_before"] == "High"
    # After step 1, override clears and points drop
    assert step1["band_after"] == "Low"

    # End state if all done
    assert plan["new_band_if_all_done"] == "Low"
    assert plan["would_be_cleared_if_all_done"] is True


def test_user_correction_3_skipped_collector_wording():
    # User Correction 3 on Section G6 / E4
    from app.services.scorecard.remediation import _get_action_template
    action_text = _get_action_template(
        ruleset=RULESET_V2,
        signal_key="web",
        rule_id="R-WEB-01",
        skip_reason="skipped_nonremediable_override",
        remediable=False,
    )
    expected_wording = (
        "Not checked: a non-remediable block already applies; these checks run automatically "
        "if the block is lifted (e.g., if a false-positive match dispute is upheld)."
    )
    assert action_text == expected_wording


# =====================================================================
# 6. CIRCUIT BREAKER (Section E2)
# =====================================================================
@pytest.mark.asyncio
async def test_circuit_breaker_sliding_window_state_machine():
    cb = CircuitBreaker("test_provider")

    # Initial state: CLOSED -> can execute
    assert await cb.can_execute() is True

    # 1 failure -> still CLOSED
    await cb.record_failure()
    assert await cb.can_execute() is True

    # 2 failures -> still CLOSED
    await cb.record_failure()
    assert await cb.can_execute() is True

    # 3 failures -> transitions to OPEN
    await cb.record_failure()
    assert await cb.can_execute() is False

    # Success resets breaker to CLOSED
    await cb.record_success()
    assert await cb.can_execute() is True


# =====================================================================
# 7. WHAT-IF SIMULATION (Section G3)
# =====================================================================
def test_pure_what_if_simulation():
    now = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)
    base_obs = {
        "gst": {"fields": {"gstin.status": "cancelled", "gstin.verification_level": "live"}},
    }

    # Simulate GSTIN active
    hypothetical = {
        "gstin.status": "active",
        "gstin.verification_level": "live",
    }
    sim_res = simulate_what_if(RULESET_V2, base_obs, hypothetical, now)

    assert sim_res["total_points"] == 0
    assert sim_res["points_band"] == "Low"
    assert "blocked_by" in sim_res
    assert "cleared_by_tier" in sim_res
    assert isinstance(sim_res["cleared_by_tier"], dict)


# =====================================================================
# 8. CLEARANCE ENDPOINT & PETTY EXCEPTION (Section C4, User Correction 2)
# =====================================================================
from unittest.mock import AsyncMock, MagicMock
from app.api.vendors import get_vendor_clearance
from app.models import Vendor, RiskScore, VendorDecision


def _no_flags():
    """The score's stored rule results: no non-remediable override, nothing awaiting review."""
    res = MagicMock()
    res.all.return_value = []
    return res


@pytest.mark.asyncio
async def test_clearance_petty_exception():
    vendor_id = "v-petty-123"
    now = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)

    # Low-tier active vendor
    vendor = MagicMock(spec=Vendor)
    vendor.id = vendor_id
    vendor.status = "active"
    vendor.vendor_tier = "petty"   # vendors.vendor_tier: petty | standard | strategic

    # Provisional score (due diligence in progress)
    score = MagicMock(spec=RiskScore)
    score.rating_status = "provisional"
    score.is_provisional = True
    score.final_band = "Unrated"
    score.points_band = "Low"
    score.score = 0.15
    score.blocked_by = []
    score.override_rule_ids = []
    score.provisional_reasons = []

    # Case A: spend 40,000 INR <= 50,000 threshold -> Cleared under petty exception
    db_mock = AsyncMock()
    db_mock.get.return_value = vendor
    score_res = MagicMock()
    score_res.scalars().first.return_value = score
    dec_res = MagicMock()
    dec_res.scalars().first.return_value = None
    db_mock.execute.side_effect = [score_res, dec_res, _no_flags()]

    res = await get_vendor_clearance(vendor_id=vendor_id, purpose="purchase", spend_amount=40000.0, db=db_mock)
    data = res.data
    assert data["cleared"] is True
    assert "cleared_under_petty_exception" in data["reasons"]

    # Case B: spend 60,000 INR > 50,000 threshold -> Not cleared
    db_mock.execute.side_effect = [score_res, dec_res, _no_flags()]
    res_b = await get_vendor_clearance(vendor_id=vendor_id, purpose="purchase", spend_amount=60000.0, db=db_mock)
    assert res_b.data["cleared"] is False
    assert "rating_provisional" in res_b.data["reasons"]

    # Case C: standard tier vendor with 40,000 INR -> Not cleared (petty exception only for petty tier)
    vendor_std = MagicMock(spec=Vendor)
    vendor_std.status = "active"
    vendor_std.vendor_tier = "standard"
    db_mock.get.return_value = vendor_std
    db_mock.execute.side_effect = [score_res, dec_res, _no_flags()]
    res_c = await get_vendor_clearance(vendor_id=vendor_id, purpose="purchase", spend_amount=40000.0, db=db_mock)
    assert res_c.data["cleared"] is False

    # Case D: override active -> Overrides strictly block petty exception
    score_ov = MagicMock(spec=RiskScore)
    score_ov.rating_status = "provisional"
    score_ov.is_provisional = True
    score_ov.final_band = "High"
    score_ov.points_band = "Low"
    score_ov.score = 0.20
    score_ov.blocked_by = ["R-GST-01"]
    score_ov.override_rule_ids = ["R-GST-01"]
    score_ov.provisional_reasons = []

    db_mock.get.return_value = vendor
    score_ov_res = MagicMock()
    score_ov_res.scalars().first.return_value = score_ov
    nonrem_res = MagicMock()
    nonrem_res.all.return_value = []                      # R-GST-01 is remediable
    db_mock.execute.side_effect = [score_ov_res, dec_res, nonrem_res]
    res_d = await get_vendor_clearance(vendor_id=vendor_id, purpose="purchase", spend_amount=40000.0, db=db_mock)
    assert res_d.data["cleared"] is False
    assert any("override_R-GST-01" in r for r in res_d.data["reasons"])


# =====================================================================
# 9. PURPOSE-BASED CLEARANCE & ACTIVATION DEADLOCK (User Correction 2)
# =====================================================================
@pytest.mark.asyncio
async def test_clearance_activation_deadlock_prevention():
    vendor_id = "v-onboard-99"

    # Vendor in 'onboarding' status
    vendor_onboarding = MagicMock(spec=Vendor)
    vendor_onboarding.id = vendor_id
    vendor_onboarding.status = "onboarding"
    vendor_onboarding.vendor_tier = "standard"

    # Assessed score
    score_assessed = MagicMock(spec=RiskScore)
    score_assessed.rating_status = "assessed"
    score_assessed.is_provisional = False
    score_assessed.final_band = "Low"
    score_assessed.points_band = "Low"
    score_assessed.score = 0.05
    score_assessed.blocked_by = []
    score_assessed.override_rule_ids = []
    score_assessed.provisional_reasons = []

    db_mock = AsyncMock()
    db_mock.get.return_value = vendor_onboarding
    score_res = MagicMock()
    score_res.scalars().first.return_value = score_assessed
    dec_res = MagicMock()
    dec_res.scalars().first.return_value = None

    # 1. purpose='activation' on onboarding status succeeds (deadlock avoided!)
    db_mock.execute.side_effect = [score_res, dec_res, _no_flags()]
    res_act = await get_vendor_clearance(vendor_id=vendor_id, purpose="activation", db=db_mock)
    assert res_act.data["cleared"] is True

    # 2. purpose='activation' fails closed if checks are provisional
    score_prov = MagicMock(spec=RiskScore)
    score_prov.rating_status = "provisional"
    score_prov.is_provisional = True
    score_prov.final_band = "Unrated"
    score_prov.points_band = "Low"
    score_prov.score = 0.05
    score_prov.blocked_by = []
    score_prov.override_rule_ids = []
    score_prov.provisional_reasons = []
    score_prov_res = MagicMock()
    score_prov_res.scalars().first.return_value = score_prov

    db_mock.execute.side_effect = [score_prov_res, dec_res, _no_flags()]
    res_act_prov = await get_vendor_clearance(vendor_id=vendor_id, purpose="activation", db=db_mock)
    assert res_act_prov.data["cleared"] is False
    assert "rating_provisional" in res_act_prov.data["reasons"]

    # 3. purpose='purchase' on onboarding status fails (purchases require 'active' vendor)
    db_mock.execute.side_effect = [score_res, dec_res, _no_flags()]
    res_purch = await get_vendor_clearance(vendor_id=vendor_id, purpose="purchase", db=db_mock)
    assert res_purch.data["cleared"] is False
    assert "vendor_status_onboarding_not_active" in res_purch.data["reasons"]


# =====================================================================
# 10. DECISIONS & OVERDUE CONDITIONS (Section C4)
# =====================================================================
@pytest.mark.asyncio
async def test_clearance_decisions_and_overdue_conditions():
    vendor_id = "v-dec-55"
    vendor = MagicMock(spec=Vendor)
    vendor.id = vendor_id
    vendor.status = "active"
    vendor.vendor_tier = "standard"

    score = MagicMock(spec=RiskScore)
    score.rating_status = "assessed"
    score.is_provisional = False
    score.final_band = "Medium"
    score.points_band = "Medium"
    score.score = 0.35
    score.blocked_by = []
    score.override_rule_ids = []
    score.provisional_reasons = []

    score_res = MagicMock()
    score_res.scalars().first.return_value = score

    # Case A: approve_with_conditions with future condition -> Cleared
    dec_pending = MagicMock(spec=VendorDecision)
    dec_pending.decision = "approve_with_conditions"
    dec_pending.expires_at = None
    dec_pending.conditions = [{"text": "Submit SOC2", "due_date": "2099-12-31", "status": "pending"}]
    dec_res_a = MagicMock()
    dec_res_a.scalars().first.return_value = dec_pending

    db_mock = AsyncMock()
    db_mock.get.return_value = vendor
    db_mock.execute.side_effect = [score_res, dec_res_a, _no_flags()]

    res_a = await get_vendor_clearance(vendor_id=vendor_id, purpose="purchase", db=db_mock)
    assert res_a.data["cleared"] is True

    # Case B: approve_with_conditions with overdue condition -> NOT cleared
    dec_overdue = MagicMock(spec=VendorDecision)
    dec_overdue.decision = "approve_with_conditions"
    dec_overdue.expires_at = None
    dec_overdue.conditions = [{"text": "Submit SOC2", "due_date": "2020-01-01", "status": "pending"}]
    dec_res_b = MagicMock()
    dec_res_b.scalars().first.return_value = dec_overdue

    db_mock.execute.side_effect = [score_res, dec_res_b, _no_flags()]
    res_b = await get_vendor_clearance(vendor_id=vendor_id, purpose="purchase", db=db_mock)
    assert res_b.data["cleared"] is False
    assert "condition_overdue" in res_b.data["reasons"]

    # Case C: reject decision -> NOT cleared
    dec_reject = MagicMock(spec=VendorDecision)
    dec_reject.decision = "reject"
    dec_reject.expires_at = None
    dec_reject.conditions = []
    dec_res_c = MagicMock()
    dec_res_c.scalars().first.return_value = dec_reject

    db_mock.execute.side_effect = [score_res, dec_res_c, _no_flags()]
    res_c = await get_vendor_clearance(vendor_id=vendor_id, purpose="purchase", db=db_mock)
    assert res_c.data["cleared"] is False
    assert "decision_rejected" in res_c.data["reasons"]


# =====================================================================
# 11. MODEL PACKAGE UNIMPORTABLE REPLAY (Section F1)
# =====================================================================
def test_model_package_unimportable_replay():
    """Section F1: Evaluator operates on observations alone.
    Replaying evaluations requires NO torch/transformers/sklearn/joblib.
    """
    # Checked in a fresh interpreter: other tests in this process (the
    # Legal-BERT clause tests) legitimately import transformers/torch.
    import subprocess, sys
    probe = ("import sys; import app.services.scorecard.engine, app.services.scorecard.default_ruleset; "
             "bad = [p for p in ('torch', 'transformers', 'sklearn', 'joblib') if p in sys.modules]; "
             "print(','.join(bad)); sys.exit(1 if bad else 0)")
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True,
                         cwd=__import__("os").path.join(__import__("os").path.dirname(__file__), ".."))
    assert out.returncode == 0, f"evaluator imports ML packages: {out.stdout} {out.stderr[-300:]}"

    now = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)
    obs = {
        "sanctions": {"fields": {"sanctions.status": "no_match"}},
        "jurisdiction": {"fields": {"country.is_domestic": True, "country.prohibited": False, "country.high_risk": False}},
    }
    # Evaluates purely via deterministic ruleset logic
    res = evaluate_risk(RULESET_V2, obs, now)
    assert res["total_points"] == 0
    assert "rating_status" in res
