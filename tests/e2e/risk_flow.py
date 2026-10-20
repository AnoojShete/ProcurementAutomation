"""Vendor risk analysis (deterministic scorecard, merged from updated_risk)
and its integration with the rest of the platform, end to end through the
gateway:

    python tests/e2e/risk_flow.py

  module       recompute, summary, explanation, history, replay, remediation
               plan, what-if, clearance, post-score decisions, evidence,
               disputes, weekly monitoring, ruleset governance, access rules
  integration  sanctions match -> High through a hard override; contract
               signing asks for an acknowledgement exactly when the vendor
               isn't cleared; a High vendor adds a finance approval step
               (approval.high_risk_vendor_requires_finance); RFQ scoring and
               the vendor scorecard read the band; risk.score.updated reaches
               the notification log; onboarding validation still works.

Needs the demo data (Acme) and the sanctions list (Rosoboronexport is the
sanctioned demo vendor from reset-demo). Rules it changes are put back.
"""
import os
import sys
import time
import uuid

import requests

GW = os.getenv("GATEWAY", "http://localhost:8080") + "/api"
PASSWORD = "DemoPass123!"
ACME = "11111111-1111-1111-1111-111111111111"
RUN = uuid.uuid4().hex[:6].upper()
results = []
H = {}


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(f"  {'✓' if cond else '✗'} {name}" + (f"  [{detail}]" if detail and not cond else ""))
    return bool(cond)


def step(title):
    print(f"\n── {title}")


def login(role):
    for _ in range(5):
        r = requests.post(f"{GW}/auth/login", json={"email": f"{role}@demo.example.com", "password": PASSWORD})
        if r.status_code != 429:
            break
        time.sleep(15)
    check(f"login {role}", r.status_code == 200, r.text[:120])
    return {"Authorization": f"Bearer {r.json()['data']['access_token']}"}


def get(path, role="finance"):
    return requests.get(f"{GW}{path}", headers=H[role])


def post(path, body=None, role="finance"):
    return requests.post(f"{GW}{path}", headers=H[role], json=body or {})


def poll(fn, until, timeout=60, interval=3):
    deadline, last = time.time() + timeout, None
    while time.time() < deadline:
        last = fn()
        if until(last):
            return last
        time.sleep(interval)
    return last


def set_rule(key, value):
    r = requests.patch(f"{GW}/admin/business-rules/{key}", headers=H["admin"],
                       json={"new_value": value, "justification": "risk e2e"})
    check(f"rule {key} = {value!r}", r.status_code == 200, r.text[:150])


def recompute(vid):
    r = post(f"/vendors/{vid}/risk/recompute")
    ok = r.status_code in (200, 202)
    summary = poll(lambda: get(f"/vendors/{vid}/risk"), lambda x: x.status_code == 200, timeout=60)
    return ok, r, summary.json().get("data") if summary is not None and summary.status_code == 200 else {}


def module():
    step("Scoring a vendor")
    ok, r, s = recompute(ACME)
    check("finance recomputes Acme's risk", ok, f"{r.status_code} {r.text[:200]}")
    check("requester can't recompute -> 403", post(f"/vendors/{ACME}/risk/recompute", role="requester").status_code == 403)
    check("summary has band, points and rating status",
          s.get("final_band") in ("Low", "Medium", "High", "Unrated") and s.get("rating_status") in ("assessed", "provisional", "not_rated")
          and s.get("total_points") is not None, {k: s.get(k) for k in ("final_band", "rating_status", "total_points")})
    check("legacy risk_band kept for older readers", s.get("risk_band") == s.get("final_band"))
    score_id = s.get("score_id")

    exp = get(f"/vendors/{ACME}/risk/explanation")
    e = exp.json().get("data") or {}
    rules = e.get("signals") or []
    check("explanation lists each signal's rule result", exp.status_code == 200 and len(rules) > 0, exp.text[:200])
    check("points add up (sum check) and groups are shown", bool(e.get("groups")) and e.get("sum_check") not in (None, False),
          str(e.get("sum_check"))[:120])
    check("each rule says assessed / not assessed with points",
          all("status" in x and "points" in x for x in rules), str(rules[:1])[:200])
    hist = get(f"/vendors/{ACME}/risk/history")
    check("history returned", hist.status_code == 200 and len(hist.json().get("data") or []) >= 1, hist.text[:150])
    rep = get(f"/vendors/{ACME}/risk/{score_id}/replay")
    rd = rep.json().get("data") or {}
    check("replay reproduces the stored score (same snapshot hash)", rep.status_code == 200 and rd.get("equal") is True
          and rd.get("stored_snapshot_sha256") == rd.get("replayed_snapshot_sha256"), rep.text[:250])
    plan = get(f"/vendors/{ACME}/risk/remediation-plan")
    check("remediation plan returned", plan.status_code == 200 and "steps" in (plan.json().get("data") or {})
          and (plan.json()["data"].get("current_rating_status") == s.get("rating_status")), plan.text[:150])
    wi = post(f"/vendors/{ACME}/risk/what-if", {"hypothetical_fields": {}})
    check("what-if simulation (finance)", wi.status_code == 200, wi.text[:200])
    check("what-if is finance/admin only", post(f"/vendors/{ACME}/risk/what-if", {}, role="approver").status_code == 403)
    bundle = get(f"/vendors/{ACME}/risk/{score_id}/bundle")
    check("audit bundle (finance)", bundle.status_code == 200, bundle.text[:150])
    check("audit bundle hidden from requesters", get(f"/vendors/{ACME}/risk/{score_id}/bundle", "requester").status_code == 403)

    step("Clearance and post-score decisions")
    c = get(f"/vendors/{ACME}/clearance?purpose=contract&spend_amount=100000").json()["data"]
    check("clearance answers cleared + reasons", isinstance(c.get("cleared"), bool) and isinstance(c.get("reasons"), list), c)
    check("clearance for an unknown vendor -> 404", get(f"/vendors/{uuid.uuid4()}/clearance").status_code == 404)
    body = {"decision": "accept_risk", "justification": f"risk e2e {RUN}: accepted for the demo", "expires_in_days": 30}
    f = post(f"/vendors/{ACME}/decisions", body)
    check("accepting a risk is admin-only (finance -> 403)", f.status_code == 403, f.text[:150])
    d = post(f"/vendors/{ACME}/decisions", body, role="admin")
    check("admin records a decision (accept risk, 30 days)", d.status_code == 200, d.text[:200])
    check("approver can't record decisions -> 403", post(f"/vendors/{ACME}/decisions", {"decision": "approve", "justification": "x"},
                                                         role="approver").status_code == 403)
    c2 = get(f"/vendors/{ACME}/clearance?purpose=contract&spend_amount=100000").json()["data"]
    check("an accepted risk clears the vendor (while active)", c2.get("cleared") is True and c2.get("post_score_decision") == "accept_risk", c2)
    if (d.json().get("data") or {}).get("decided_by"):
        check("decision recorded with the caller's identity", d.json()["data"]["decided_by"] == "admin@demo.example.com",
              d.json()["data"].get("decided_by"))

    step("Evidence, disputes, monitoring, rulesets")
    ev = post(f"/vendors/{ACME}/evidence", {"evidence_type": "iso27001", "title": f"ISO 27001 certificate {RUN}",
                                            "valid_until": "2027-12-31"}, role="requester")
    check("requester submits evidence -> pending review", ev.status_code == 200 and ev.json()["data"]["status"] == "pending_review", ev.text[:200])
    ev2 = post(f"/vendors/{ACME}/evidence", {"evidence_type": "iso27001", "title": f"ISO 27001 (finance) {RUN}", "valid_until": "2027-12-31"})
    check("finance evidence is accepted directly", ev2.status_code == 200 and ev2.json()["data"]["status"] == "accepted", ev2.text[:200])
    check("evidence register lists both", sum(1 for x in get(f"/vendors/{ACME}/evidence").json()["data"] if RUN in x.get("title", "")) == 2)
    dis = post(f"/vendors/{ACME}/risk/disputes", {"score_id": score_id, "reason": "Delivery record ignores the March orders."}, role="requester")
    check("a dispute can be raised", dis.status_code == 200, dis.text[:200])
    weekly = get("/vendors/risk-monitoring/weekly-report", "admin")
    check("weekly monitoring report", weekly.status_code == 200, weekly.text[:150])
    active = get("/admin/risk-rulesets/active", "admin")
    check("active ruleset through the gateway", active.status_code == 200 and active.json()["data"], active.text[:150])
    check("only admin saves a draft ruleset", post("/admin/risk-rulesets/draft", {}, role="finance").status_code == 403)


def integration():
    step("Sanctions match -> High through a hard override")
    vendors = get("/vendors/?limit=500", "admin").json()["data"]
    sanctioned = next((v for v in vendors if v["name"].startswith("Rosoboronexport")), None)
    if check("sanctioned demo vendor present", sanctioned is not None, "run ./scripts/reset-demo.sh"):
        post(f"/vendors/{sanctioned['id']}/screen-sanctions")
        sc = (get(f"/vendors/{sanctioned['id']}/sanctions").json().get("data") or {}).get("latest") or {}
        _, _, s = recompute(sanctioned["id"])
        cleared_by_finance = sc.get("status") == "cleared"
        check("sanctions screening finds the match", sc.get("status") in ("potential_match", "cleared"), sc.get("status"))
        if not cleared_by_finance:
            check("an open sanctions match makes the vendor High", s.get("final_band") == "High", s.get("final_band"))
            check("... through an override rule", bool(s.get("override_rule_ids") or s.get("blocked_by")), s)
        cl = get(f"/vendors/{sanctioned['id']}/clearance?purpose=purchase&spend_amount=1000").json()["data"]
        check("a sanctioned vendor is never cleared for purchase", cl["cleared"] is False, cl)

        step("Budget routing reads the band")
        set_rule("approval.high_risk_vendor_requires_finance", True)
        req = poll(lambda: requests.post(f"{GW}/requests/", headers=H["requester"], json={
            "request_type": "hardware", "requested_by": "x", "department": f"E2E Risk {RUN}", "amount": 1000, "currency": "INR",
            "vendor_id": sanctioned["id"], "items": [{"name": "Cable", "quantity": 1, "unit_price": 1000}]}).json()["data"],
            lambda x: "finance_head" in (x.get("approval_chain") or []), timeout=40, interval=4)
        check("High vendor adds a finance step to a manager-tier request",
              "finance_head" in req["approval_chain"] and "high_risk_vendor" in (req.get("budget_check") or {}).get("routing", []),
              f"{req['approval_chain']} {req.get('budget_check')}")
        set_rule("approval.high_risk_vendor_requires_finance", False)
        requests.post(f"{GW}/requests/{req['id']}/reject", headers=H["approver"], json={"comments": "risk e2e"})

    step("Contract signing asks for an acknowledgement exactly when needed")
    contracts = get("/contracts/?limit=200", "admin").json()["data"]
    unsigned = next((c for c in contracts if c["status"] == "pending_signature" and c.get("vendor_id")), None)
    if unsigned is None:
        r = post("/contracts/generate", {"purchase_request_id": "22222222-2222-2222-2222-222222222222", "template_name": "hardware_purchase"})
        unsigned = r.json().get("data")
    if check("an unsigned contract to sign", unsigned is not None):
        detail = get(f"/contracts/{unsigned['id']}", "approver").json()["data"]
        vr = detail.get("vendor_risk") or {}
        check("contract shows the vendor's clearance before signing", "acknowledgement_required" in vr and "rating_status" in vr, vr)
        body = {"signer_name": "Vaidehi", "signer_email": "approver@demo.example.com", "legal_consent": True}
        r = post(f"/contracts/{unsigned['id']}/sign", body, role="approver")
        if vr.get("acknowledgement_required"):
            check("not cleared: signing without acknowledgement -> 409",
                  r.status_code == 409 and "acknowledg" in r.text.lower(), f"{r.status_code} {r.text[:150]}")
            r = post(f"/contracts/{unsigned['id']}/sign", {**body, "risk_acknowledged": True}, role="approver")
            check("with the acknowledgement it signs", r.status_code == 200 and r.json()["data"]["status"] == "signed", r.text[:200])
            cert = get(f"/contracts/{unsigned['id']}/signature-certificate", "approver").json()["data"]
            check("certificate records the acknowledged risk", (cert.get("vendor_risk_at_signing") or {}).get("acknowledged") is True,
                  cert.get("vendor_risk_at_signing"))
        else:
            check("cleared vendor: signs without acknowledgement", r.status_code == 200, r.text[:200])

    step("Other readers of the band")
    card = get(f"/vendors/{ACME}/scorecard").json().get("data") or {}
    summary = get(f"/vendors/{ACME}/risk").json()["data"]
    check("vendor performance scorecard carries the current band", card.get("risk_band") == summary["final_band"],
          f"{card.get('risk_band')} vs {summary['final_band']}")
    listed = next(v for v in get("/vendors/?limit=500", "admin").json()["data"] if v["id"] == ACME)
    check("vendor list shows the band", listed.get("risk_band") == summary["final_band"], f"{listed.get('risk_band')}")
    log = poll(lambda: requests.get(f"{GW}/notifications/log?limit=200", headers=H["admin"]).json()["data"],
               lambda rows: any(n["event_type"] == "risk.score.updated" and ACME in str(n) for n in rows), timeout=40)
    check("risk.score.updated reaches the notification log",
          any(n["event_type"] == "risk.score.updated" and ACME in str(n) for n in log))
    on = requests.post(f"{GW}/vendors/onboard/validate", headers=H["finance"], json={
        "name": f"Risk E2E Onboard {RUN} Pvt Ltd", "country": "IN", "gstin": "27AAPFU0939F1ZV"})
    check("onboarding validation still works (with country)", on.status_code in (200, 422), f"{on.status_code} {on.text[:150]}")


def main():
    for role in ("requester", "approver", "finance", "admin"):
        H[role] = login(role)
    module()
    integration()
    failed = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("Failed:\n  " + "\n  ".join(failed))
        sys.exit(1)


if __name__ == "__main__":
    main()
