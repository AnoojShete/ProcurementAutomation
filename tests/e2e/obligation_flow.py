"""Contract obligation tracking (feature expansion Phase 2), end to end
through the gateway against the running stack.

    python tests/e2e/obligation_flow.py

A SaaS request is approved, its contract goes out by itself and is signed
(HMAC e-sign webhook), the background sweep reads the obligations, finance
confirms them, a month's downtime turns into a service credit that the
invoice ledger then warns about, and a licence with more users than the
contract allows is flagged as a breach. The licence limit is linked to a
demo licence and confirmed with one seat fewer than it has assigned;
nothing in the licence itself is changed. Data stays behind like every
e2e suite's (./scripts/reset-demo.sh clears it).
"""
import hashlib
import hmac
import json
import os
import sys
import time
import uuid
from datetime import date, datetime, timezone

import requests

GW = os.getenv("GATEWAY", "http://localhost:8080") + "/api"
PASSWORD = "DemoPass123!"
ESIGN_SECRET = os.getenv("ESIGN_WEBHOOK_SECRET", "dev-esign-secret-change-me")
RUN = uuid.uuid4().hex[:6].upper()
results = []


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


def poll(fn, until, timeout=120, interval=3):
    deadline, last = time.time() + timeout, None
    while time.time() < deadline:
        last = fn()
        if until(last):
            return last
        time.sleep(interval)
    return last


def sign(contract_id):
    body = {"provider_event_id": f"evt-obl-{RUN}", "contract_id": contract_id, "signed_by": "vendor@e2e.example",
            "signed_at": datetime.now(timezone.utc).isoformat()}
    sig = hmac.new(ESIGN_SECRET.encode(), json.dumps(body, sort_keys=True, separators=(",", ":")).encode(),
                   hashlib.sha256).hexdigest()
    return requests.post(f"{GW}/webhooks/esign", json=dict(body, signature=sig))


def main():
    requester, approver, finance, admin = (login(r) for r in ("requester", "approver", "finance", "admin"))

    step("A SaaS request, approved; its contract goes out by itself")
    vendor = requests.get(f"{GW}/vendors/?limit=50", headers=admin).json()["data"][0]
    seats, price = 10, 1200
    r = requests.post(f"{GW}/requests/", headers=requester, json={
        "request_type": "saas", "requested_by": "ignored", "department": "IT", "amount": seats * price,
        "currency": "INR", "vendor_id": vendor["id"], "comments": f"obligation e2e {RUN}",
        "items": [{"name": f"Design tool seats {RUN}", "quantity": seats, "unit_price": price}]})
    check("request created", r.status_code == 200, r.text[:150])
    pr = r.json()["data"]
    # Every level of the chain (manager, then finance for this amount).
    for who, h in (("approver", approver), ("finance", finance)):
        cur = requests.get(f"{GW}/requests/{pr['id']}", headers=admin).json()["data"]
        if cur["status"] != "pending_approval":
            break
        r = requests.post(f"{GW}/requests/{pr['id']}/approve", headers=h, json={"comments": "obligation e2e"})
        check(f"{who} approves", r.status_code == 200, r.text[:150])
        time.sleep(2)
    pr = poll(lambda: requests.get(f"{GW}/requests/{pr['id']}", headers=admin).json()["data"],
              lambda x: x["status"] == "approved", timeout=30, interval=2)
    check("request approved", pr["status"] == "approved", pr["status"])
    contract = poll(lambda: next((c for c in requests.get(f"{GW}/contracts/?limit=50", headers=admin).json()["data"]
                                  if c["purchase_request_id"] == pr["id"]), None),
                    lambda c: c is not None and c["status"] == "pending_signature", timeout=60, interval=2)
    if not check("contract sent for signature", contract and contract["status"] == "pending_signature",
                 contract and contract["status"]):
        return
    cid = contract["id"]
    detail = requests.get(f"{GW}/contracts/{cid}", headers=admin).json()["data"]
    check("SaaS template with the seat count", detail["template_used"] == "saas_subscription"
          and f"up to {seats} named users" in " ".join(detail["contract_text"].split()), detail["template_used"])

    step("Before signature there is nothing to track")
    r = requests.get(f"{GW}/contracts/{cid}/obligations", headers=finance).json()["data"]
    check("no obligations, not reading", r["obligations"] == [] and r["reading"] is False, str(r)[:150])

    step("Signed: the sweep reads the obligations (within a minute)")
    check("signed webhook -> 200", sign(cid).status_code == 200)
    view = poll(lambda: requests.get(f"{GW}/contracts/{cid}/obligations", headers=finance).json()["data"],
                lambda v: v["extracted_at"] is not None, timeout=150, interval=5)
    found = {o["type"]: o for o in view["obligations"]}
    check("read after signing", view["extracted_at"] is not None, str(view)[:150])
    check("all nine SaaS obligations found", set(found) == {
        "sla_uptime", "license_limit", "price_cap", "audit_rights", "minimum_commitment", "post_termination",
        "data_protection", "liability_cap", "insurance"}, sorted(found))
    check("all waiting to be confirmed", all(o["status"] == "to_confirm" for o in found.values()))
    check("licence limit read as the request's seat count", found.get("license_limit", {}).get("value", {}).get("seats") == seats,
          found.get("license_limit", {}).get("value"))
    check("SLA terms read", found.get("sla_uptime", {}).get("value") ==
          {"uptime_pct": 99.9, "credit_pct_per_step": 10.0, "step_pct": 0.1, "credit_cap_pct": 50.0},
          found.get("sla_uptime", {}).get("value"))
    rq = requests.get(f"{GW}/contracts/{cid}/obligations", headers=requester)
    check("requester of the request can read them", rq.status_code == 200, str(rq.status_code))

    step("Confirming")
    sla, lim = found["sla_uptime"], found["license_limit"]
    r = requests.patch(f"{GW}/contracts/obligations/{sla['id']}/confirm", headers=approver, json={})
    check("approver can't confirm -> 403", r.status_code == 403, str(r.status_code))
    r = requests.patch(f"{GW}/contracts/obligations/{sla['id']}/confirm", headers=finance,
                       json={"owner_email": "it-owner@demo.example.com", "confirmed_by": "mallory@evil.test"})
    ob = r.json().get("data") or {}
    check("finance confirms the SLA", r.status_code == 200 and ob.get("status") == "open", r.text[:150])
    check("confirmer from the token, not the body", ob.get("confirmed_by") == "finance@demo.example.com", ob.get("confirmed_by"))
    month_end = date.today().replace(day=1)
    check("monthly review due at month end", ob.get("recurrence") == "monthly" and ob.get("due_date", "")[:7] == month_end.isoformat()[:7],
          f"{ob.get('recurrence')} {ob.get('due_date')}")

    step("A month's downtime becomes a service credit")
    period = f"{date.today().year}-{date.today().month:02d}"
    r = requests.post(f"{GW}/contracts/obligations/{sla['id']}/downtime", headers=approver,
                      json={"period": period, "measured_uptime_pct": 99.6, "note": "e2e outage"})
    credit = (r.json().get("data") or {}).get("credit") or {}
    fee = seats * price / 12
    check("99.6 % against 99.9 % -> 30 % credit", r.status_code == 200 and credit.get("credit_pct") == 30, r.text[:200])
    check("credit = 30 % of the monthly fee", abs(credit.get("credit_amount", 0) - round(fee * 0.3, 2)) < 0.01,
          f"{credit.get('credit_amount')} vs {round(fee * 0.3, 2)}")
    check("expected on the next invoice (rule default)", credit.get("status") == "expected", credit.get("status"))
    again = requests.post(f"{GW}/contracts/obligations/{sla['id']}/downtime", headers=approver,
                          json={"period": period, "measured_uptime_pct": 99.0})
    check("same month twice -> 422", again.status_code == 422, str(again.status_code))

    step("The invoice ledger knows about it")
    ledger = requests.get(f"{GW}/invoices/ledger/{pr['id']}", headers=finance).json()["data"]
    check("ledger lists the expected credit", [c["id"] for c in ledger.get("expected_credits", [])] == [credit.get("id")],
          ledger.get("expected_credits"))
    sim = requests.post(f"{GW}/invoices/match?dry_run=true", headers=finance, json={
        "document_id": str(uuid.uuid4()), "vendor_id": vendor["id"], "total": seats * price,
        "lines": [{"description": f"Design tool seats {RUN}", "quantity": seats, "unit_price": price}],
        "po_reference": pr["id"]}).json()["data"]
    check("an invoice for this request carries the credit note",
          sim.get("request_id") == pr["id"] and any("service credit" in n for n in sim.get("notes", [])),
          f"{sim.get('status')} {sim.get('notes')}")
    r = requests.post(f"{GW}/contracts/sla-credits/{credit.get('id')}", headers=finance, json={"status": "applied"})
    check("finance marks it applied", r.status_code == 200 and r.json()["data"]["status"] == "applied", r.text[:150])
    ledger = requests.get(f"{GW}/invoices/ledger/{pr['id']}", headers=finance).json()["data"]
    check("no longer expected", ledger.get("expected_credits") == [], ledger.get("expected_credits"))

    step("A licence with more users than the contract allows")
    lic = max(requests.get(f"{GW}/inventory/", headers=admin).json()["data"]["licenses"],
              key=lambda x: x.get("assigned_seats") or 0)
    used = lic.get("assigned_seats") or 0
    check("a demo licence with users", used > 1, f"{lic['app_name']} {used}")
    r = requests.patch(f"{GW}/contracts/obligations/{lim['id']}/confirm", headers=finance,
                       json={"value": {**lim["value"], "seats": used - 1}, "license_id": lic["id"]})
    check("limit confirmed one seat below what is assigned", r.status_code == 200, r.text[:150])
    ob = poll(lambda: requests.get(f"{GW}/contracts/{cid}/obligations", headers=finance).json()["data"],
              lambda v: next(o for o in v["obligations"] if o["id"] == lim["id"])["status"] == "breached",
              timeout=100, interval=5)
    lim_now = next(o for o in ob["obligations"] if o["id"] == lim["id"])
    check("sweep flags the breach", lim_now["status"] == "breached", lim_now["status"])
    check("breach event says why", any(e["kind"] == "breach" and e["details"].get("source") == "licence"
                                       for e in lim_now["events"]), lim_now["events"][:2])
    shown = requests.get(f"{GW}/contracts/obligations/by-license/{lic['id']}", headers=approver).json()["data"]
    check("licence page sees the limit", any(o["id"] == lim["id"] for o in shown))
    check("requester can't list licence limits",
          requests.get(f"{GW}/contracts/obligations/by-license/{lic['id']}", headers=requester).status_code == 403)
    r = requests.patch(f"{GW}/contracts/obligations/{lim['id']}/confirm", headers=finance,
                       json={"value": {**lim["value"], "seats": used}})
    check("finance corrects the seat number", r.status_code == 200, r.text[:150])
    lim_now = poll(lambda: next(o for o in requests.get(f"{GW}/contracts/{cid}/obligations", headers=finance)
                                .json()["data"]["obligations"] if o["id"] == lim["id"]),
                   lambda o: o["status"] == "open", timeout=100, interval=5)
    check("stays open once within the limit", lim_now["status"] == "open", lim_now["status"])

    step("Lifecycle")
    audit = found["audit_rights"]
    r = requests.post(f"{GW}/contracts/obligations/{audit['id']}/actions", headers=finance, json={"action": "met"})
    check("unconfirmed can't be met -> 422", r.status_code == 422, str(r.status_code))
    requests.patch(f"{GW}/contracts/obligations/{audit['id']}/confirm", headers=finance, json={})
    first = requests.get(f"{GW}/contracts/{cid}/obligations", headers=finance).json()["data"]
    due = next(o for o in first["obligations"] if o["id"] == audit["id"])["due_date"]
    r = requests.post(f"{GW}/contracts/obligations/{audit['id']}/actions", headers=approver, json={"action": "met"})
    nxt = (r.json().get("data") or {}).get("due_date")
    check("yearly audit window met -> next year's", r.status_code == 200 and nxt and int(nxt[:4]) == int(due[:4]) + 1,
          f"{due} -> {nxt}")
    r = requests.post(f"{GW}/contracts/obligations/{found['insurance']['id']}/actions", headers=approver,
                      json={"action": "waived", "note": "x"})
    check("approver can't waive -> 403", r.status_code == 403, str(r.status_code))
    r = requests.post(f"{GW}/contracts/obligations/{found['insurance']['id']}/actions", headers=finance,
                      json={"action": "waived"})
    check("waive without a reason -> 422", r.status_code == 422, str(r.status_code))
    r = requests.post(f"{GW}/contracts/obligations/{found['insurance']['id']}/actions", headers=finance,
                      json={"action": "waived", "note": "covered by the group policy"})
    check("finance waives with a reason", r.status_code == 200 and r.json()["data"]["status"] == "waived", r.text[:150])

    step("Rules")
    grouped = requests.get(f"{GW}/admin/business-rules", headers=admin).json()["data"]
    rules = {x["rule_key"]: x for group in grouped.values() for x in group}
    for key in ("contract.obligation_reminder_days", "contract.obligation_model_min_confidence",
                "contract.sla_credit_auto_expect"):
        check(f"{key} seeded", key in rules)
    bad = requests.patch(f"{GW}/admin/business-rules/contract.obligation_reminder_days", headers=admin,
                         json={"new_value": [0], "justification": "obligation e2e"})
    check("reminder days must be whole days -> 400", bad.status_code == 400, str(bad.status_code))

    failed = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("Failed:\n  " + "\n  ".join(failed))
        sys.exit(1)


if __name__ == "__main__":
    main()
