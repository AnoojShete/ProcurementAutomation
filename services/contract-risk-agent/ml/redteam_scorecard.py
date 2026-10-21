"""Red-team set for the deterministic vendor risk scorecard and the
clearance gate (FR-04).

Each profile is an attempt to get a risky vendor through, or a check that a
safe one isn't blocked for the wrong reason. The expected outcome was
written from the ruleset (app/services/scorecard/default_ruleset.py) and
the clearance rules (app/services/clearance.py) before running. The profiles
go through the real code: `evaluate_risk` (the pure engine) and
`clearance.decide`, with no database.

    python ml/redteam_scorecard.py      # prints the table, writes docs/results/risk-redteam.json

tests/test_risk_redteam.py runs every profile on each test run.

The Agent document's own red-team list lives in the team's Drive and was
never added to the repository, so these profiles are derived from what that
document requires of the risk agent: hard overrides (sanctions, GSTIN, bank,
jurisdiction) decide alone, missing data is excluded and never counted as
safe, a vendor is never shown as Low while checks are outstanding, and every
score can be explained and replayed.
"""
import json
import os
import sys
from copy import deepcopy
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from app.services import clearance  # noqa: E402
from app.services.scorecard.default_ruleset import get_default_ruleset  # noqa: E402
from app.services.scorecard.engine import evaluate_risk  # noqa: E402

NOW = datetime(2026, 10, 21, 9, 0, tzinfo=timezone.utc)
PETTY_THRESHOLD = 50000.0

# A clean, established Indian vendor: every check run today and clear.
CLEAN = {
    "sanctions": {"sanctions.status": "no_match"},
    "gst": {"gstin.status": "active", "gstin.verification_level": "live"},
    "bank": {"bank.status": "valid"},
    "jurisdiction": {"country.is_domestic": True},
    "web": {"web.ssl_grade": "A"},
    "email": {"email.dmarc_policy": "reject", "email.spf_present": True},
    "breach": {"breach.count_5y": 0},
    "certification": {"cert.required": True, "cert.status": "valid"},
    "financial": {"fin.rating_class": "investment"},
    "company_age": {"age.basis": "incorporation", "age.years": 10},
    "delivery_sla": {"sla.orders_delivered": 20, "sla.on_time_pct": 96},
    "feedback": {"fbk.count_12m": 10, "fbk.mean_12m": 4.5},
    "incidents": {"inc.history_available": True, "inc.count_24m": 0},
    "adverse_media": {"media.qualifying_articles": 0},
}
POOR_PERFORMANCE = {
    "delivery_sla": {"sla.orders_delivered": 20, "sla.on_time_pct": 40},      # 15
    "feedback": {"fbk.count_12m": 8, "fbk.mean_12m": 1.5},                    # 12
    "incidents": {"inc.history_available": True, "inc.count_24m": 3},         # 8
}
ACCEPT_RISK = {"decision": "accept_risk", "expires_at": (NOW + timedelta(days=20)).isoformat()}


def obs(**changes):
    """CLEAN with some signals changed; a value of None removes the signal
    (never checked)."""
    out = deepcopy(CLEAN)
    for key, fields in changes.items():
        if fields is None:
            out.pop(key, None)
        else:
            out[key] = fields
    return out


PROFILES = [
    {"name": "Clean, established vendor", "attack": "control: nothing wrong",
     "observations": obs(), "expected": {"final_band": "Low", "rating_status": "assessed", "cleared": True}},
    {"name": "Sanctions match behind a perfect record",
     "attack": "excellent delivery and finances to outweigh a sanctions hit",
     "observations": obs(sanctions={"sanctions.status": "match"}),
     "expected": {"final_band": "High", "override": "R-SAN-01", "cleared": False}},
    {"name": "Sanctions match, admin accepts the risk",
     "attack": "an admin's time-boxed 'accept risk' to clear a sanctioned vendor",
     "observations": obs(sanctions={"sanctions.status": "match"}), "decision": ACCEPT_RISK,
     "expected": {"final_band": "High", "override": "R-SAN-01", "cleared": False,
                  "reason": "override_R-SAN-01"}},
    {"name": "Prohibited country", "attack": "clean paperwork from a prohibited jurisdiction",
     "country": "KP", "observations": obs(jurisdiction={"country.prohibited": True, "country.is_domestic": False}),
     "expected": {"final_band": "High", "override": "R-JUR-01", "cleared": False}},
    {"name": "Cancelled GSTIN", "attack": "invoice from a deregistered entity with a good history",
     "observations": obs(gst={"gstin.status": "cancelled", "gstin.verification_level": "live"}),
     "expected": {"final_band": "High", "override": "R-GST-01", "cleared": False}},
    {"name": "Cancelled GSTIN, admin accepts the risk for 20 days",
     "attack": "remediable override: a documented, time-boxed acceptance is allowed",
     "observations": obs(gst={"gstin.status": "cancelled", "gstin.verification_level": "live"}),
     "decision": ACCEPT_RISK, "expected": {"final_band": "High", "cleared": True, "reason": "risk_accepted_until_"}},
    {"name": "Brand-new vendor, nothing checked", "attack": "no data at all, hoping for a default Low",
     "observations": {}, "expected": {"final_band": "Unrated", "rating_status": "not_rated", "cleared": False}},
    {"name": "Only identity checked", "attack": "partial checks, 0 points, hoping to show as Low",
     "observations": {k: CLEAN[k] for k in ("sanctions", "gst", "bank")},
     "expected": {"final_band": "Unrated", "rating_status": "provisional", "cleared": False,
                  "reason": "rating_provisional"}},
    {"name": "Stale sanctions check", "attack": "a clear sanctions result from three days ago (valid for one)",
     "observations": obs(), "stale": {"sanctions": 3},
     "expected": {"final_band": "Unrated", "rating_status": "provisional", "cleared": False}},
    {"name": "Country of incorporation missing", "attack": "leave the country blank to skip jurisdiction rules",
     "country": None, "observations": obs(),
     "expected": {"final_band": "Unrated", "rating_status": "provisional", "cleared": False}},
    {"name": "Petty vendor, small purchase, checks incomplete",
     "attack": "control: the petty exception for a small purchase", "tier": "petty", "spend": 40000,
     "observations": {k: CLEAN[k] for k in ("sanctions", "gst", "bank")},
     "expected": {"final_band": "Unrated", "cleared": True, "reason": "cleared_under_petty_exception"}},
    {"name": "Petty vendor with a possible sanctions match",
     "attack": "use the petty exception while a sanctions match awaits review", "tier": "petty", "spend": 40000,
     "observations": {"sanctions": {"sanctions.status": "possible_match"}, "gst": CLEAN["gst"], "bank": CLEAN["bank"]},
     "expected": {"cleared": False, "reason": "rating_provisional"}},
    {"name": "Petty vendor, purchase just over the limit", "attack": "split-free purchase above the petty limit",
     "tier": "petty", "spend": 50001, "observations": {k: CLEAN[k] for k in ("sanctions", "gst", "bank")},
     "expected": {"cleared": False, "reason": "rating_provisional"}},
    {"name": "Poor performer", "attack": "late, badly rated, frequent incidents, otherwise compliant",
     "observations": obs(**POOR_PERFORMANCE),
     "expected": {"final_band": "Medium", "points": 35, "rating_status": "assessed", "cleared": True}},
    {"name": "Poor performer with weak finances and recent breaches",
     "attack": "many medium problems, no single override",
     "observations": obs(**POOR_PERFORMANCE, financial={"fin.rating_class": "default"},
                         breach={"breach.count_5y": 2, "breach.latest_within_12m": True},
                         certification={"cert.required": True, "cert.status": "none"}, web={"web.ssl_grade": "F"}),
     "expected": {"final_band": "High", "points": 53, "cleared": False, "reason": "high_risk_band"}},
    {"name": "Approved when Low, now High", "attack": "an old approval keeping a vendor cleared after it got worse",
     "observations": obs(**POOR_PERFORMANCE, financial={"fin.rating_class": "default"},
                         breach={"breach.count_5y": 2, "breach.latest_within_12m": True},
                         certification={"cert.required": True, "cert.status": "none"}, web={"web.ssl_grade": "F"}),
     "decision": {"decision": "approve_with_conditions", "conditions": [{"text": "SOC 2", "due_date": "2099-01-01"}]},
     "expected": {"final_band": "High", "cleared": False, "reason": "approval_ineligible"}},
    {"name": "Approved with a condition now overdue", "attack": "ignore the condition attached to an approval",
     "observations": obs(**POOR_PERFORMANCE),
     "decision": {"decision": "approve_with_conditions", "conditions": [{"text": "SOC 2", "due_date": "2026-01-01"}]},
     "expected": {"final_band": "Medium", "cleared": False, "reason": "condition_overdue"}},
    {"name": "Rejected by a reviewer", "attack": "a Low score after a person rejected the vendor",
     "observations": obs(), "decision": {"decision": "reject"},
     "expected": {"final_band": "Low", "cleared": False, "reason": "decision_rejected"}},
    {"name": "New supplier with no order history", "attack": "control: missing history must not count against it",
     "observations": obs(delivery_sla={"sla.orders_delivered": 1}, feedback={"fbk.count_12m": 0},
                         incidents={"inc.history_available": False}),
     "expected": {"final_band": "Low", "points": 0, "rating_status": "assessed", "cleared": True}},
    {"name": "Adverse media only", "attack": "a single detect-only finding can't make a vendor High",
     "observations": obs(adverse_media={"media.high_severity_count": 1, "media.qualifying_articles": 1}),
     "expected": {"final_band": "Low", "points": 3, "cleared": True}},
    {"name": "Offboarded vendor with a clean score", "attack": "buy from a vendor that was offboarded",
     "status": "offboarded", "observations": obs(),
     "expected": {"final_band": "Low", "cleared": False, "reason": "vendor_status_offboarded_not_active"}},
    {"name": "Vendor still onboarding", "attack": "buy before activation", "status": "onboarding",
     "observations": obs(), "expected": {"cleared": False, "reason": "vendor_status_onboarding_not_active"}},
]


def run_profile(p: dict) -> dict:
    ruleset = get_default_ruleset()
    stale = p.get("stale", {})
    observations = {
        key: {"signal_key": key, "status": "ok", "fields": fields,
              "fetched_at": (NOW - timedelta(days=stale.get(key, 0))).isoformat()}
        for key, fields in p["observations"].items()
    }
    context = {"name": p["name"], "spend_tier": p.get("tier", "standard"), "inherent_tier": None,
               "country": p.get("country", "IN")}
    result = evaluate_risk(ruleset, observations, NOW, vendor_context=context)
    non_remediable = {r["rule_id"] for r in result["rule_results"] if r.get("override_band") and not r["remediable"]}
    view = clearance.ScoreView(
        rating_status=result["rating_status"], final_band=result["final_band"], points_band=result["points_band"],
        score=result["score_float"], override_rule_ids=result["override_rule_ids"], non_remediable=non_remediable,
        provisional_reasons=result["provisional_reasons"], blocked_by=result["blocked_by"],
        pending_review={r["signal_key"] for r in result["rule_results"] if r["status"] == "review_pending"})
    d = p.get("decision")
    decision = clearance.DecisionView(
        d["decision"], datetime.fromisoformat(d["expires_at"]) if d.get("expires_at") else None,
        d.get("conditions", [])) if d else None
    gate = clearance.decide(view, decision, purpose=p.get("purpose", "purchase"), spend_amount=p.get("spend"),
                            vendor_tier=p.get("tier", "standard"), vendor_status=p.get("status", "active"),
                            petty_threshold=PETTY_THRESHOLD, now=NOW)
    got = {"final_band": result["final_band"], "points": result["total_points"],
           "rating_status": result["rating_status"], "overrides": result["override_rule_ids"],
           "cleared": gate["cleared"], "reasons": gate["reasons"]}
    exp = p["expected"]
    problems = []
    for key in ("final_band", "points", "rating_status", "cleared"):
        if key in exp and exp[key] != got[key]:
            problems.append(f"{key}: expected {exp[key]}, got {got[key]}")
    if "override" in exp and exp["override"] not in got["overrides"]:
        problems.append(f"override {exp['override']} not triggered ({got['overrides']})")
    if "reason" in exp and not any(r.startswith(exp["reason"]) for r in got["reasons"]):
        problems.append(f"reason {exp['reason']} missing ({got['reasons']})")
    return {"name": p["name"], "attack": p["attack"], "expected": exp, "got": got, "passed": not problems,
            "problems": problems}


def run_all() -> list[dict]:
    return [run_profile(p) for p in PROFILES]


def main():
    results = run_all()
    for r in results:
        print(f"{'✓' if r['passed'] else '✗'} {r['name']:<55} {r['got']['final_band']:<8} "
              f"{r['got']['points']:>3} pts  {'cleared' if r['got']['cleared'] else 'blocked':<8} "
              f"{', '.join(r['got']['reasons'])}" + (f"\n    {'; '.join(r['problems'])}" if r["problems"] else ""))
    passed = sum(r["passed"] for r in results)
    print(f"\n{passed}/{len(results)} profiles as expected")
    root = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
    out = os.path.join(root, "docs", "results", "risk-redteam.json")
    if os.path.isdir(os.path.dirname(out)):
        with open(out, "w") as f:
            json.dump({"run_at": NOW.isoformat(), "passed": passed, "total": len(results), "profiles": results}, f,
                      indent=2, default=str)
        print("→ docs/results/risk-redteam.json")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
