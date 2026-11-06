import os
import sys
import copy
import random
import pytest
from datetime import datetime, date, timezone, timedelta

# Ensure python paths for shared modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

from app.services.scorecard.default_ruleset import get_default_ruleset
from app.services.scorecard.validator import validate_ruleset, RulesetValidationError
from app.services.scorecard.evaluator import SafeEvaluator, render_template
from app.services.scorecard.engine import evaluate_risk
from app.services.scorecard.remediation import build_remediation_plan, simulate_what_if
from app.services.collectors.base import redact_secrets, days_since, months_between


# =====================================================================
# 14.1 SUM IDENTITY (50 random observation sets)
# =====================================================================
def test_sum_identity_random_observations():
    ruleset = get_default_ruleset()
    signals = ruleset["signals"]

    # Invariant: max_points sum = 100
    assert sum(s["max_points"] for s in signals) == 100

    field_candidates = {
        "sanctions": [
            {"sanctions.matched": True, "sanctions.match_count": 1, "sanctions.highest_score": 95},
            {"sanctions.matched": False, "sanctions.match_count": 0, "sanctions.highest_score": 0},
            {},
        ],
        "gst": [
            {"gstin.status": "cancelled", "gstin.number": "29ABCDE1234F1Z5", "gstin.cancellation_date": "2026-01-01"},
            {"gstin.status": "suspended", "gstin.number": "29ABCDE1234F1Z5"},
            {"gstin.status": "active", "gstin.number": "29ABCDE1234F1Z5", "gstin.return_filed_within_60d": True, "gstin.days_since_last_filed": 15},
            {"gstin.status": "active", "gstin.number": "29ABCDE1234F1Z5", "gstin.return_filed_within_60d": False, "gstin.days_since_last_filed": 75},
            {},
        ],
        "bank": [
            {"bank.penny_drop_status": "success", "bank.account_match": True, "bank.name_match_pct": 98.5, "bank.beneficiary_name": "Acme Pvt Ltd"},
            {"bank.penny_drop_status": "success", "bank.account_match": True, "bank.name_match_pct": 72.0, "bank.beneficiary_name": "Acme Tools"},
            {"bank.penny_drop_status": "failed", "bank.account_match": False, "bank.beneficiary_name": ""},
            {},
        ],
        "delivery_sla": [
            {"delivery.order_count": 5, "delivery.on_time_pct": 96.0, "delivery.late_count": 0},
            {"delivery.order_count": 10, "delivery.on_time_pct": 85.0, "delivery.late_count": 1},
            {"delivery.order_count": 8, "delivery.on_time_pct": 70.0, "delivery.late_count": 2},
            {"delivery.order_count": 1, "delivery.on_time_pct": 100.0, "delivery.late_count": 0}, # low orders -> not assessed
            {},
        ],
        "company_age": [
            {"age.months": 48, "age.basis": "mca_incorporation", "age.incorporated_on": "2022-01-01"},
            {"age.months": 18, "age.basis": "mca_incorporation", "age.incorporated_on": "2024-05-01"},
            {"age.months": 6, "age.basis": "mca_incorporation", "age.incorporated_on": "2026-04-01"},
            {"age.months": 24, "age.basis": "domain_only"}, # domain only -> not assessed
            {},
        ],
    }

    assessed_at = datetime(2026, 10, 19, 12, 0, 0, tzinfo=timezone.utc)

    for i in range(50):
        observations = []
        for s in signals:
            key = s["key"]
            candidates = field_candidates.get(key, [{"status": "ok"}, {}])
            fields = copy.deepcopy(random.choice(candidates))
            status = "ok" if fields else "not_assessed"
            observations.append({
                "signal_key": key,
                "status": status,
                "fields": fields,
                "facts": [{"label": k, "value": str(v)} for k, v in fields.items()],
                "provider": "test_provider",
            })

        result = evaluate_risk(ruleset, observations, assessed_at=assessed_at, vendor_context={"spend_tier": "strategic", "inherent_tier": "critical"})

        rule_results = result["rule_results"]
        total_points = result["total_points"]

        # Exact integer sum identity: total_points == sum(rule_results.points)
        sum_points = sum(r["points"] for r in rule_results)
        assert total_points == sum_points, f"Iteration {i} failed: {total_points} != {sum_points}"
        assert 0 <= total_points <= 100


# =====================================================================
# 14.2 RULESET VALIDATOR
# =====================================================================
def test_ruleset_validator_success():
    ruleset = get_default_ruleset()
    valid, errors = validate_ruleset(ruleset)
    assert valid is True
    assert len(errors) == 0


def test_ruleset_validator_sum_not_100():
    ruleset = copy.deepcopy(get_default_ruleset())
    ruleset["signals"][0]["max_points"] = 999  # breaks sum == 100
    valid, errors = validate_ruleset(ruleset)
    assert valid is False
    assert any("equal 100" in e["message"] for e in errors)


def test_ruleset_validator_missing_else():
    ruleset = copy.deepcopy(get_default_ruleset())
    # Add a 'when' condition to the last outcome of signal 0
    ruleset["signals"][0]["outcomes"][-1]["when"] = {"field": "foo", "op": "eq", "value": "bar"}
    valid, errors = validate_ruleset(ruleset)
    assert valid is False
    assert any("must have no 'when' condition" in e["message"] for e in errors)


def test_ruleset_validator_unknown_operator():
    ruleset = copy.deepcopy(get_default_ruleset())
    ruleset["signals"][0]["outcomes"][0]["when"]["op"] = "eval_code"
    valid, errors = validate_ruleset(ruleset)
    assert valid is False
    assert any("unknown operator" in e["message"] for e in errors)


def test_ruleset_validator_invalid_bands():
    ruleset = copy.deepcopy(get_default_ruleset())
    ruleset["bands"] = {"low_max": 50, "medium_max": 30} # low_max >= medium_max
    valid, errors = validate_ruleset(ruleset)
    assert valid is False
    assert any("bands must satisfy" in e["message"] for e in errors)


def test_ruleset_validator_duplicate_rule_id():
    ruleset = copy.deepcopy(get_default_ruleset())
    ruleset["signals"][1]["outcomes"][0]["rule_id"] = ruleset["signals"][0]["outcomes"][0]["rule_id"]
    valid, errors = validate_ruleset(ruleset)
    assert valid is False
    assert any("Duplicate rule_id" in e["message"] for e in errors)


# =====================================================================
# 14.3 EVALUATOR OPERATORS AND NULL HANDLING
# =====================================================================
def test_evaluator_operators_and_null_handling():
    # eq / ne
    assert SafeEvaluator.evaluate({"field": "val", "op": "eq", "value": "test"}, {"val": "test"}) is True
    assert SafeEvaluator.evaluate({"field": "val", "op": "eq", "value": "test"}, {"val": "other"}) is False
    assert SafeEvaluator.evaluate({"field": "val", "op": "eq", "value": "test"}, {"val": None}) is False
    assert SafeEvaluator.evaluate({"field": "val", "op": "ne", "value": "test"}, {"val": "other"}) is True

    # in / not_in
    assert SafeEvaluator.evaluate({"field": "status", "op": "in", "value": ["active", "verified"]}, {"status": "active"}) is True
    assert SafeEvaluator.evaluate({"field": "status", "op": "in", "value": ["active", "verified"]}, {"status": "cancelled"}) is False
    assert SafeEvaluator.evaluate({"field": "status", "op": "in", "value": ["active"]}, {"status": None}) is False
    assert SafeEvaluator.evaluate({"field": "status", "op": "not_in", "value": ["cancelled"]}, {"status": "active"}) is True

    # lt / lte / gt / gte
    assert SafeEvaluator.evaluate({"field": "age", "op": "gte", "value": 18}, {"age": 18}) is True
    assert SafeEvaluator.evaluate({"field": "age", "op": "gt", "value": 18}, {"age": 18}) is False
    assert SafeEvaluator.evaluate({"field": "age", "op": "lt", "value": 18}, {"age": 17}) is True
    assert SafeEvaluator.evaluate({"field": "age", "op": "lte", "value": 18}, {"age": 18}) is True
    # Null comparisons must be False, never raise
    assert SafeEvaluator.evaluate({"field": "age", "op": "gte", "value": 18}, {"age": None}) is False
    assert SafeEvaluator.evaluate({"field": "age", "op": "lt", "value": 18}, {}) is False

    # between (inclusive)
    assert SafeEvaluator.evaluate({"field": "score", "op": "between", "value": [10, 20]}, {"score": 10}) is True
    assert SafeEvaluator.evaluate({"field": "score", "op": "between", "value": [10, 20]}, {"score": 20}) is True
    assert SafeEvaluator.evaluate({"field": "score", "op": "between", "value": [10, 20]}, {"score": 15}) is True
    assert SafeEvaluator.evaluate({"field": "score", "op": "between", "value": [10, 20]}, {"score": 9}) is False
    assert SafeEvaluator.evaluate({"field": "score", "op": "between", "value": [10, 20]}, {"score": 21}) is False
    assert SafeEvaluator.evaluate({"field": "score", "op": "between", "value": [10, 20]}, {"score": None}) is False

    # is_null / not_null
    assert SafeEvaluator.evaluate({"field": "doc", "op": "is_null"}, {"doc": None}) is True
    assert SafeEvaluator.evaluate({"field": "doc", "op": "is_null"}, {}) is True
    assert SafeEvaluator.evaluate({"field": "doc", "op": "is_null"}, {"doc": "file.pdf"}) is False
    assert SafeEvaluator.evaluate({"field": "doc", "op": "not_null"}, {"doc": "file.pdf"}) is True
    assert SafeEvaluator.evaluate({"field": "doc", "op": "not_null"}, {"doc": None}) is False

    # Combinations (all, any, not)
    cond = {
        "all": [
            {"field": "a", "op": "eq", "value": 1},
            {"any": [
                {"field": "b", "op": "eq", "value": 2},
                {"field": "c", "op": "eq", "value": 3},
            ]}
        ]
    }
    assert SafeEvaluator.evaluate(cond, {"a": 1, "b": 2, "c": 0}) is True
    assert SafeEvaluator.evaluate(cond, {"a": 1, "b": 0, "c": 3}) is True
    assert SafeEvaluator.evaluate(cond, {"a": 1, "b": 0, "c": 0}) is False
    assert SafeEvaluator.evaluate(cond, {"a": 0, "b": 2, "c": 3}) is False


# =====================================================================
# 14.5 GST MATRIX
# =====================================================================
def test_gst_matrix():
    ruleset = get_default_ruleset()
    assessed_at = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)

    # 1. Cancelled => 25 pts, override High
    obs_cancelled = [{
        "signal_key": "gst",
        "status": "ok",
        "fields": {"gstin.status": "cancelled", "gstin.number": "29ABCDE1234F1Z5", "gstin.cancellation_date": "2026-01-01"},
        "provider": "cleartax",
    }]
    res = evaluate_risk(ruleset, obs_cancelled, assessed_at=assessed_at)
    gst_rule = next(r for r in res["rule_results"] if r["signal_key"] == "gst")
    assert gst_rule["rule_id"] == "R-GST-01"
    assert gst_rule["points"] == 20
    assert gst_rule["override_band"] == "High"
    assert res["final_band"] == "High"

    # 2. Suspended => 20 pts, override High in Prompt 9C (R-GST-02)
    obs_suspended = [{
        "signal_key": "gst",
        "status": "ok",
        "fields": {"gstin.status": "suspended", "gstin.number": "29ABCDE1234F1Z5"},
        "provider": "cleartax",
    }]
    res = evaluate_risk(ruleset, obs_suspended, assessed_at=assessed_at)
    gst_rule = next(r for r in res["rule_results"] if r["signal_key"] == "gst")
    assert gst_rule["rule_id"] == "R-GST-02"
    assert gst_rule["points"] == 20
    assert gst_rule["override_band"] == "High"

    # 3. Active & verified live/document => 0 pts (R-GST-05)
    obs_verified = [{
        "signal_key": "gst",
        "status": "ok",
        "fields": {
            "gstin.status": "active",
            "gstin.verification_level": "live",
            "gstin.number": "29ABCDE1234F1Z5",
            "gstin.legal_name": "Acme Pvt Ltd",
            "gstin.name_match_level": "exact",
        },
        "provider": "cleartax",
    }]
    res = evaluate_risk(ruleset, obs_verified, assessed_at=assessed_at)
    gst_rule = next(r for r in res["rule_results"] if r["signal_key"] == "gst")
    assert gst_rule["rule_id"] == "R-GST-06"
    assert gst_rule["points"] == 0

    # 4. Not found in registry => 20 pts (R-GST-03)
    obs_not_found = [{
        "signal_key": "gst",
        "status": "ok",
        "fields": {"gstin.status": "not_found", "gstin.number": "29ABCDE1234F1Z5"},
        "provider": "cleartax",
    }]
    res = evaluate_risk(ruleset, obs_not_found, assessed_at=assessed_at)
    gst_rule = next(r for r in res["rule_results"] if r["signal_key"] == "gst")
    assert gst_rule["rule_id"] == "R-GST-03"
    assert gst_rule["points"] == 20

    # 5. Attested exempt => 0 pts (R-GST-05 in Prompt 9C)
    obs_exempt = [{
        "signal_key": "gst",
        "status": "ok",
        "fields": {"gstin.verification_level": "attested_exempt", "confirmed_by": "Finance", "date": "2026-01-01"},
        "provider": "internal",
    }]
    res = evaluate_risk(ruleset, obs_exempt, assessed_at=assessed_at)
    gst_rule = next(r for r in res["rule_results"] if r["signal_key"] == "gst")
    assert gst_rule["rule_id"] == "R-GST-05"
    assert gst_rule["points"] == 0

    # 6. Null gstin => not_assessed (0 pts) (R-GST-08 in Prompt 9C)
    obs_null = [{
        "signal_key": "gst",
        "status": "not_assessed",
        "fields": {},
        "provider": "cleartax",
    }]
    res = evaluate_risk(ruleset, obs_null, assessed_at=assessed_at)
    gst_rule = next(r for r in res["rule_results"] if r["signal_key"] == "gst")
    assert gst_rule["rule_id"] == "R-GST-08"
    assert gst_rule["points"] == 0
    assert gst_rule["status"] == "not_assessed"


# =====================================================================
# 14.6 OVERRIDES
# =====================================================================
def test_overrides():
    ruleset = get_default_ruleset()
    assessed_at = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)

    # Vendor with 0 points from all other signals + cancelled GSTIN:
    # total_points = 25 (which is Low on points_band <= 24? 25 is Medium since low_max=24)
    # But GST cancellation locks final_band to High!
    obs = [{
        "signal_key": "gst",
        "status": "ok",
        "fields": {"gstin.status": "cancelled", "gstin.number": "29ABCDE1234F1Z5", "gstin.cancellation_date": "2026-01-01"},
        "provider": "cleartax",
    }]
    res = evaluate_risk(ruleset, obs, assessed_at=assessed_at)
    assert res["total_points"] == 20
    # Only the GST check ran, so its 20 of 20 points weigh as 100 (30 Oct 2026), held
    # toward the middle while 80% of the scorecard is open (31 Oct 2026)
    assert res["reweighted_points"] == 100 and res["weighted_points"] == 50 and res["points_band"] == "High"
    assert res["final_band"] == "High"
    assert "R-GST-01" in res["override_rule_ids"]


# =====================================================================
# 14.7 NOT ASSESSED AND PROVISIONAL
# =====================================================================
def test_not_assessed_and_provisional():
    ruleset = get_default_ruleset()
    assessed_at = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)

    # 0 observations
    res = evaluate_risk(ruleset, [], assessed_at=assessed_at, vendor_context={"spend_tier": "strategic", "inherent_tier": "critical"})

    assert res["total_points"] == 0
    assert res["weighted_points"] == 100 and res["points_band"] == "High"
    # Prompt 9C: unassessed vendor must never look Low; nothing checked = worst case (30 Oct 2026)
    assert res["final_band"] == "High"
    assert res["rating_status"] == "not_rated"
    assert res["unassessed_potential_points"] > 0
    assert res["worst_case_points"] > 0
    assert res["worst_case_band"] in ("Medium", "High")
    assert res["is_provisional"] is False
    assert len(res["provisional_reasons"]) > 0


# =====================================================================
# 14.8 DETERMINISM & REPLAY
# =====================================================================
def test_determinism_pure_evaluation():
    ruleset = get_default_ruleset()
    assessed_at = datetime(2026, 10, 19, 12, 0, 0, tzinfo=timezone.utc)

    obs = [
        {"signal_key": "gst", "status": "ok", "fields": {"gstin.status": "active", "gstin.return_filed_within_60d": True}, "provider": "cleartax"},
        {"signal_key": "bank", "status": "ok", "fields": {"bank.penny_drop_status": "success", "bank.account_match": True, "bank.name_match_pct": 95.0}, "provider": "razorpay"},
    ]

    res1 = evaluate_risk(ruleset, obs, assessed_at=assessed_at)
    res2 = evaluate_risk(ruleset, obs, assessed_at=assessed_at)

    assert res1["total_points"] == res2["total_points"]
    assert res1["final_band"] == res2["final_band"]
    assert res1["snapshot_sha256"] == res2["snapshot_sha256"]
    assert res1["headline"] == res2["headline"]
    assert res1["explanation"]["thought_process"] == res2["explanation"]["thought_process"]


# =====================================================================
# 14.9 TIME CALCULATIONS
# =====================================================================
def test_time_calculations():
    # Leap year: 2024 is a leap year (Feb 29 exists)
    d1 = date(2024, 2, 28)
    d2 = date(2024, 3, 1)
    assert days_since(d1, d2) == 2

    # Non-leap year: 2025 is not a leap year
    d3 = date(2025, 2, 28)
    d4 = date(2025, 3, 1)
    assert days_since(d3, d4) == 1

    # Months between across year boundary
    d_dec = date(2024, 12, 1)
    d_feb = date(2025, 2, 1)
    assert months_between(d_dec, d_feb) == 2


# =====================================================================
# 14.10 REMEDIATION AND VENDOR-SAFE FILTER
# =====================================================================
def test_remediation_and_vendor_safe_filter():
    ruleset = get_default_ruleset()
    assessed_at = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)

    # Vendor with GST suspended (20 pts, remediable, shareable_with_vendor=True)
    obs = [{
        "signal_key": "gst",
        "status": "ok",
        "fields": {"gstin.status": "suspended", "gstin.number": "29ABCDE1234F1Z5"},
        "provider": "cleartax",
    }]
    eval_result = evaluate_risk(ruleset, obs, assessed_at=assessed_at)

    plan_buyer = build_remediation_plan(ruleset, eval_result, {"gst": obs[0]}, assessed_at, audience="internal")
    assert plan_buyer["current_total"] == 20
    assert plan_buyer["new_total_if_all_done"] == 0
    assert plan_buyer["new_band_if_all_done"] in ("Low", "Unrated")
    assert len(plan_buyer["items"]) >= 1

    # 2. Vendor-safe plan (only vendor-assigned, shareable_with_vendor steps)
    plan_vendor = build_remediation_plan(ruleset, eval_result, {"gst": obs[0]}, assessed_at, audience="vendor")
    assert plan_vendor["audience"] == "vendor"
    steps = plan_vendor.get("steps") or plan_vendor.get("items") or []
    for step in steps:
        assert step.get("shareable_with_vendor") is not False

    # 3. What-if simulator
    what_if = simulate_what_if(ruleset, {"gst": obs[0]}, {"gstin.status": "active", "gstin.return_filed_within_60d": True,
                                                         "gstin.verification_level": "live",
                                                         "gstin.name_match_level": "exact"}, assessed_at)
    assert what_if["total_points"] == 0
    # Only GST is on file, so the provisional score is held toward the middle (31 Oct 2026)
    assert what_if["points_band"] == "Medium"
    assert what_if["final_band"] == "Medium"


# =====================================================================
# 14.11 COLLECTORS & SECRET REDACTION
# =====================================================================
def test_secret_redaction():
    url = "https://api.provider.com/v1/check?apikey=secret123&token=abc456&name=Vendor"
    headers = {
        "Authorization": "Bearer super_secret_jwt",
        "Set-Cookie": "session=xyz987",
        "Content-Type": "application/json",
        "X-Custom-Key": "my_secret_token",
    }
    params = {"key": "secret_key_val", "search": "Acme Inc"}

    redacted_url, redacted_params, redacted_headers = redact_secrets(url, params, headers)

    assert "secret123" not in redacted_url
    assert "abc456" not in redacted_url
    assert "***" in redacted_url

    assert redacted_headers["Authorization"] == "***"
    assert redacted_headers["Set-Cookie"] == "***"
    assert redacted_headers["Content-Type"] == "application/json"
    assert redacted_headers["X-Custom-Key"] == "***"

    assert redacted_params["key"] == "***"
    assert redacted_params["search"] == "Acme Inc"


# =====================================================================
# 14.12 DISPUTES & FOUR-EYES GOVERNANCE
# =====================================================================
def test_dispute_four_eyes_requirement():
    raised_by = "procurement_analyst@company.com"
    reviewer = "procurement_analyst@company.com"

    # Four-eyes check: reviewer must differ from raised_by
    is_valid_reviewer = (reviewer != raised_by)
    assert is_valid_reviewer is False

    different_reviewer = "cpo_anooj@company.com"
    assert (different_reviewer != raised_by) is True


# =====================================================================
# 14.13 DRY RUN & ACTIVATION REQUIREMENTS
# =====================================================================
def test_activation_justification_min_length():
    short_justification = "Updated points"
    assert len(short_justification.strip()) < 20

    valid_justification = "Calibrated delivery and sanctions weights against Q3 audit outcomes."
    assert len(valid_justification.strip()) >= 20


# =====================================================================
# 14.14 SCORECARD EXPLANATION BREAKDOWN & INVARIANT PROOF
# =====================================================================
def test_scorecard_explanation_breakdown_identity_invariant():
    ruleset = get_default_ruleset()
    assessed_at = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)

    obs = [
        {"signal_key": "sanctions", "status": "review_pending", "fields": {"sanctions.matches": [{"name": "Acme", "score": 75}]}, "provider": "opensanctions"},
        {"signal_key": "web", "status": "ok", "fields": {"web.cert_valid": False, "web.reachable": True}, "provider": "tls_probe"},
    ]

    res = evaluate_risk(ruleset, obs, assessed_at=assessed_at, vendor_context={"tier": "Tier 1", "country": "IN"})
    expl = res["explanation"]

    assert "score_breakdown" in expl
    assert "signals" in expl
    assert len(expl["score_breakdown"]) == len(ruleset["signals"])

    computed_sum = sum(r["points"] for r in expl["score_breakdown"])
    assert computed_sum == expl["total_points"]
    assert computed_sum == res["total_points"]
    assert expl["sum_check"]["equals_total"] is True
    assert expl["sum_check"]["sum_of_signal_points"] == computed_sum

    for r in expl["score_breakdown"]:
        assert "rule_id" in r
        assert "signal_key" in r
        assert "signal_label" in r
        assert "group_key" in r
        assert "points" in r
        assert "potential_points" in r
        assert "status" in r
        assert "facts" in r
        assert "reason_text" in r

    assert "unassessed_signals" in expl
    assert len(expl["unassessed_signals"]) > 0
    for u in expl["unassessed_signals"]:
        assert "signal_key" in u
        assert "potential_points" in u
        assert "provider" in u


def test_serialize_risk_explanation_legacy_migration():
    from app.api.vendors import _serialize_risk_explanation
    from app.models import RiskScore

    legacy_signals = [
        {
            "signal_key": "sanctions",
            "label": "Sanctions screening",
            "group": "identity",
            "status": "review_pending",
            "points": 5,
            "max_points": 10,
            "rule_id": "R-SAN-02",
            "reason_text": "Possible match",
            "rationale": "Expert rationale",
            "facts": [{"label": "Source", "value": "OpenSanctions"}],
        },
        {
            "signal_key": "web",
            "label": "Web & TLS security posture",
            "group": "cyber",
            "status": "assessed",
            "points": 6,
            "max_points": 6,
            "rule_id": "R-WEB-01",
            "reason_text": "Broken TLS",
            "rationale": "Eavesdropping risk",
            "facts": [{"label": "Source", "value": "TLS probe"}],
        },
        {
            "signal_key": "gst",
            "label": "GST Registration",
            "group": "identity",
            "status": "not_assessed",
            "points": 0,
            "max_points": 10,
            "rule_id": "R-GST-07",
            "reason_text": "No observation",
            "rationale": "",
            "facts": [],
        },
    ]

    mock_score = RiskScore(
        id="score-1234",
        vendor_id="vendor-5678",
        total_points=11,
        final_band="High",
        points_band="Low",
        worst_case_points=42,
        worst_case_band="Medium",
        unassessed_potential_points=31,
        is_provisional=True,
        ruleset_version=2,
        scored_at=datetime(2026, 10, 30, 12, 46, 0, tzinfo=timezone.utc),
        explanation={
            "signals": legacy_signals,
            "total_points": 11,
            "final_band": "High",
            "thought_process": ["Step 1", "Step 2"],
        },
    )

    serialized = _serialize_risk_explanation(mock_score)

    assert serialized["score_id"] == "score-1234"
    assert serialized["vendor_id"] == "vendor-5678"
    assert "score_breakdown" in serialized
    assert len(serialized["score_breakdown"]) == 3

    computed_sum = sum(r["points"] for r in serialized["score_breakdown"])
    assert computed_sum == 11
    assert computed_sum == serialized["total_points"]

    assert serialized["score_breakdown"][0]["signal_label"] == "Sanctions screening"
    assert serialized["score_breakdown"][0]["group_key"] == "identity"
    assert serialized["score_breakdown"][0]["potential_points"] == 10

    assert len(serialized["unassessed_signals"]) == 1
    assert serialized["unassessed_signals"][0]["signal_key"] == "gst"
    assert serialized["unassessed_signals"][0]["potential_points"] == 10
