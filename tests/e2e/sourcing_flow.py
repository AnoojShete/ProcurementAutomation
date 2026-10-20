"""Sourcing (feature expansion Phase 3), end to end through the gateway
against the running stack:

    python tests/e2e/sourcing_flow.py

  catalog    agreed price wins over the client's, expired items refused,
             pre-approval rule, a seat add-on adds licence seats on receipt
  RFQ        sealed bids hidden from every role, a real quote PDF quoting the
             RFQ reference is linked by the pipeline, weighted comparison,
             award creates the request, second round for a shortlist
  receipts   30 of 50 received: an invoice for 50 is a variance, for 30 it
             matches; the rest arrives and the request is fulfilled
  scorecard  the vendor page's figures

Needs the demo data (./scripts/seed-demo-data.sh) for the catalog and the
Acme vendor. Data stays behind like every e2e suite's; rules it changes are
put back.
"""
import hashlib
import hmac
import json
import os
import random
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "services", "document-vendor-agent", "scripts"))
from synthetic_invoice_lib import build_pdf_bytes, render_document  # noqa: E402

GW = os.getenv("GATEWAY", "http://localhost:8080") + "/api"
PASSWORD = "DemoPass123!"
ESIGN_SECRET = os.getenv("ESIGN_WEBHOOK_SECRET", "dev-esign-secret-change-me")
RUN = uuid.uuid4().hex[:6].upper()
ACME = "11111111-1111-1111-1111-111111111111"
SLACK = "33333333-0000-0000-0000-000000000002"
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


def poll(fn, until, timeout=60, interval=2):
    deadline, last = time.time() + timeout, None
    while time.time() < deadline:
        last = fn()
        if until(last):
            return last
        time.sleep(interval)
    return last


def set_rule(admin, key, value):
    r = requests.patch(f"{GW}/admin/business-rules/{key}", headers=admin,
                       json={"new_value": value, "justification": "sourcing e2e"})
    check(f"rule {key} = {value!r}", r.status_code == 200, r.text[:150])


H = {}


def get_req(rid):
    return requests.get(f"{GW}/requests/{rid}", headers=H["admin"]).json()["data"]


def approve_all(rid):
    for role in ("approver", "finance"):
        if get_req(rid)["status"] != "pending_approval":
            break
        requests.post(f"{GW}/requests/{rid}/approve", headers=H[role], json={"comments": "sourcing e2e"})
        time.sleep(2)
    return poll(lambda: get_req(rid), lambda r: r["status"] != "pending_approval", timeout=30)


def sign_contract(rid):
    """The contract goes out by itself after approval; sign it (HMAC webhook)."""
    c = poll(lambda: next((c for c in requests.get(f"{GW}/contracts/?limit=100", headers=H["admin"]).json()["data"]
                           if c["purchase_request_id"] == rid), None),
             lambda c: c is not None and c["status"] == "pending_signature", timeout=60)
    if not c:
        return None
    body = {"provider_event_id": f"evt-src-{RUN}-{rid[:8]}", "contract_id": c["id"], "signed_by": "vendor@e2e.example",
            "signed_at": datetime.now(timezone.utc).isoformat()}
    sig = hmac.new(ESIGN_SECRET.encode(), json.dumps(body, sort_keys=True, separators=(",", ":")).encode(), hashlib.sha256).hexdigest()
    requests.post(f"{GW}/webhooks/esign", json=dict(body, signature=sig))
    return poll(lambda: get_req(rid), lambda r: r["status"] == "ordered", timeout=30)


def new_request(role, **body):
    return requests.post(f"{GW}/requests/", headers=H[role], json={
        "requested_by": "ignored", "currency": "INR", "department": f"E2E Sourcing {RUN}", **body})


def catalog():
    step("Catalog")
    items = requests.get(f"{GW}/catalog/", headers=H["requester"]).json()["data"]
    skus = {i["sku"]: i for i in items}
    check("requester sees the orderable demo items", {"CAT-LAP-DELL-5540", "CAT-SEAT-SLACK", "CAT-MON-U2723"} <= set(skus), sorted(skus))
    check("an item whose price expired is hidden", "CAT-LAP-TP-E14" not in skus)
    everything = requests.get(f"{GW}/catalog/?include_unavailable=true", headers=H["finance"]).json()["data"]
    expired = next((i for i in everything if i["sku"] == "CAT-LAP-TP-E14"), None)
    check("finance sees it, marked unavailable", expired is not None and expired["available"] is False)
    r = new_request("requester", request_type="hardware", amount=1, items=[{"catalog_item_id": expired["id"], "quantity": 1}])
    check("ordering it -> 422 catalog_unavailable", r.status_code == 422 and r.json()["error"]["code"] == "catalog_unavailable", r.text[:150])
    r = requests.post(f"{GW}/catalog/", headers=H["requester"], json={"sku": "X", "name": "X", "category": "hardware", "vendor_id": ACME, "unit_price": 1})
    check("requester can't add items -> 403", r.status_code == 403)
    r = requests.post(f"{GW}/catalog/", headers=H["finance"], json={
        "sku": f"CAT-E2E-{RUN}", "name": f"E2E keyboard {RUN}", "category": "hardware", "vendor_id": ACME, "unit_price": 2500,
        "lead_time_days": 2, "warranty_months": 12, "valid_until": (date.today() + timedelta(days=90)).isoformat()})
    check("finance adds an item", r.status_code == 201, r.text[:150])
    kb = r.json()["data"]
    r = new_request("requester", request_type="saas", amount=1, items=[{"catalog_item_id": kb["id"], "quantity": 4, "unit_price": 1}])
    pr = r.json().get("data") or {}
    check("price, type and vendor come from the catalog", r.status_code == 200 and pr.get("amount") == 10000
          and pr.get("request_type") == "hardware" and pr.get("vendor_id") == ACME, r.text[:200])
    check("catalog line carries its agreed terms", (pr.get("items") or [{}])[0].get("warranty_months") == 12)
    off = requests.patch(f"{GW}/catalog/{kb['id']}", headers=H["finance"], json={"active": False})
    check("finance switches it off again (keeps the demo catalog clean)", off.status_code == 200 and off.json()["data"]["available"] is False)

    mon = skus["CAT-MON-U2723"]
    r = new_request("requester", request_type="hardware", amount=0, items=[{"catalog_item_id": mon["id"], "quantity": 1}])
    check("monitor (₹40,500) needs the manager with pre-approval off", r.json()["data"]["status"] == "pending_approval",
          r.json()["data"]["status"])
    set_rule(H["admin"], "catalog.preapproved_max_inr", 50000)
    seat = skus["CAT-SEAT-SLACK"]["id"]
    pre = poll(lambda: new_request("requester", request_type="saas", amount=0,
                                   items=[{"catalog_item_id": seat, "quantity": 2}]).json()["data"],
               lambda x: x["status"] == "approved", timeout=40, interval=4)
    check("pre-approval on: 2 seats (₹2,500, manager tier) approved at once", pre["status"] == "approved" and pre["spend_tier"] == "catalog",
          f"{pre['status']} {pre['spend_tier']}")
    mon2 = new_request("requester", request_type="hardware", amount=0, items=[{"catalog_item_id": mon["id"], "quantity": 1}]).json()["data"]
    check("the monitor (manager + finance tier) skips the manager but keeps finance",
          mon2["approval_chain"] == ["finance_head"] and "catalog_preapproved" in (mon2.get("budget_check") or {}).get("routing", []),
          f"{mon2['approval_chain']} {mon2.get('budget_check')}")
    set_rule(H["admin"], "catalog.preapproved_max_inr", 0)

    step("Seat add-on: receiving it adds licence seats")
    seats = lambda: next(l for l in requests.get(f"{GW}/inventory/", headers=H["admin"]).json()["data"]["licenses"] if l["id"] == SLACK)["total_seats"]
    before = seats()
    r = new_request("requester", request_type="saas", amount=0, items=[{"catalog_item_id": skus["CAT-SEAT-SLACK"]["id"], "quantity": 3}])
    pr = r.json()["data"]
    check("3 Slack seats at the agreed ₹1,250", pr["amount"] == 3750 and pr["items"][0]["seat_addon"] is True, r.text[:150])
    approve_all(pr["id"])
    ordered = sign_contract(pr["id"])
    check("approved, contract signed -> ordered", ordered and ordered["status"] == "ordered", ordered and ordered["status"])
    r = requests.post(f"{GW}/requests/{pr['id']}/receive", headers=H["requester"])
    check("requester marks it received", r.status_code == 200 and r.json()["data"]["status"] == "fulfilled", r.text[:150])
    check("Slack licence has 3 more seats", seats() == before + 3, f"{before} -> {seats()}")
    r = requests.post(f"{GW}/requests/{pr['id']}/receive", headers=H["requester"])
    check("receiving twice -> 409, seats added once", r.status_code == 409 and seats() == before + 3)


def rfq_flow():
    step("RFQ: sealed bids, a quote from the pipeline, award")
    vendors = [v for v in requests.get(f"{GW}/vendors/?limit=100", headers=H["admin"]).json()["data"]
               if v["status"] != "offboarded" and v["id"] != ACME][:2]
    invite = [ACME] + [v["id"] for v in vendors]
    check("three vendors to invite", len(invite) == 3)
    deadline = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    body = {"title": f"Laptop refresh {RUN}", "department": f"E2E Sourcing {RUN}", "request_type": "hardware",
            "items": [{"name": "Developer laptop", "quantity": 3}], "vendor_ids": invite, "deadline": deadline, "sealed": True}
    check("approver can't issue an RFQ -> 403", requests.post(f"{GW}/rfqs/", headers=H["approver"], json=body).status_code == 403)
    one = requests.post(f"{GW}/rfqs/", headers=H["finance"], json={**body, "vendor_ids": invite[:1]})
    check("one vendor isn't a comparison -> 422", one.status_code == 422, one.text[:120])
    r = requests.post(f"{GW}/rfqs/", headers=H["finance"], json=body)
    check("finance issues it", r.status_code == 201, r.text[:150])
    rfq = r.json()["data"]
    rid, ref = rfq["id"], rfq["reference"]
    check("reference looks like RFQ-XXXXXX", len(ref) == 10 and ref.startswith("RFQ-"), ref)
    check("requester can't see RFQs -> 403", requests.get(f"{GW}/rfqs/{rid}", headers=H["requester"]).status_code == 403)

    # Acme answers with a real quote PDF that quotes the reference.
    rng = random.Random(RUN)
    lines, quote_total = render_document(rng, "quote", "A", {"name": "Acme IT Supplies Inc", "currency": "INR"},
                                         [{"name": "Developer laptop", "quantity": 3, "unit_price": 88000.0}],
                                         f"QT-{RUN}", date.today(), "Acme Corp IT Department")
    lines.insert(lines.index("QUOTATION") + 2, f"Your reference: {ref}")
    up = requests.post(f"{GW}/documents/upload", headers=H["requester"],
                       files={"file": (f"quote_{ref}.pdf", build_pdf_bytes(lines), "application/pdf")})
    check("Acme's quote uploaded", up.status_code == 201, up.text[:120])
    linked = poll(lambda: requests.get(f"{GW}/rfqs/{rid}", headers=H["finance"]).json()["data"],
                  lambda d: any(i["vendor_id"] == ACME and i["responded_at"] for i in d["invitations"]), timeout=180, interval=5)
    check("the pipeline linked it to the RFQ", any(i["vendor_id"] == ACME and i["responded_at"] for i in linked["invitations"]),
          [(i["vendor_name"], i["responded_at"]) for i in linked["invitations"]])

    for vid, total, lead, warranty, support in ((invite[1], 255000, 21, 12, 3), (invite[2], 270000, 4, 36, 5)):
        r = requests.post(f"{GW}/rfqs/{rid}/responses", headers=H["finance"], json={
            "vendor_id": vid, "total_inr": total, "lead_time_days": lead, "warranty_months": warranty, "support_rating": support})
        check(f"quote recorded ({total})", r.status_code == 200, r.text[:150])
    outsider = requests.post(f"{GW}/rfqs/{rid}/responses", headers=H["finance"], json={"vendor_id": str(uuid.uuid4()), "total_inr": 1})
    check("a vendor that wasn't invited -> 422", outsider.status_code == 422)

    for role in ("admin", "finance", "approver"):
        view = requests.get(f"{GW}/rfqs/{rid}", headers=H[role]).json()["data"]
        hidden = view["sealed_now"] and view["comparison"] is None and all("total_inr" not in r for r in view["responses"])
        check(f"sealed: {role} sees who quoted, not amounts", hidden and len(view["responses"]) == 3, str(view["responses"])[:150])

    r = requests.post(f"{GW}/rfqs/{rid}/close", headers=H["finance"])
    check("everyone quoted, so it can close before the deadline", r.status_code == 200 and r.json()["data"]["status"] == "closed", r.text[:150])
    cmp = r.json()["data"]["comparison"]
    ranked = cmp["ranked"]
    check("comparison of all three, ranked", len(ranked) == 3 and [x["rank"] for x in ranked] == [1, 2, 3])
    check("price scored against the cheapest", max(x["scores"]["price"] for x in ranked) == 1.0)
    acme = next(x for x in ranked if x["vendor_id"] == ACME)
    check("Acme's quote total read from the PDF", abs(acme["total_inr"] - quote_total) < 1, f"{acme['total_inr']} vs {quote_total}")
    best = ranked[0]
    r = requests.post(f"{GW}/rfqs/{rid}/award", headers=H["finance"], json={"response_id": best["id"]})
    check("award -> purchase request", r.status_code == 200 and r.json()["data"]["status"] == "awarded", r.text[:200])
    req = r.json()["data"]["request"]
    check("request carries the winner and the RFQ", req["vendor_id"] == best["vendor_id"] and req["rfq_id"] == rid
          and abs(req["amount"] - best["total_inr"]) < 0.01, f"{req['vendor_id']} {req.get('rfq_id')} {req['amount']}")
    check("no 'RFQ recommended' note on an RFQ award", not any(f["code"] == "rfq_recommended" for f in req.get("sourcing_flags") or []))
    again = requests.post(f"{GW}/rfqs/{rid}/award", headers=H["finance"], json={"response_id": best["id"]})
    check("awarding twice -> 422", again.status_code == 422, str(again.status_code))

    step("RFQ: second round for a shortlist")
    r = requests.post(f"{GW}/rfqs/", headers=H["finance"], json={**body, "title": f"Monitors {RUN}", "sealed": False,
                                                                  "vendor_ids": invite[1:], "items": [{"name": "27 in monitor", "quantity": 10}]})
    r2 = r.json()["data"]
    for vid, total in ((invite[1], 400000), (invite[2], 410000)):
        requests.post(f"{GW}/rfqs/{r2['id']}/responses", headers=H["finance"], json={"vendor_id": vid, "total_inr": total})
    view = requests.get(f"{GW}/rfqs/{r2['id']}", headers=H["approver"]).json()["data"]
    check("unsealed: amounts visible while open", view["comparison"] is not None and len(view["comparison"]["ranked"]) == 2)
    early = requests.post(f"{GW}/rfqs/{r2['id']}/rounds", headers=H["finance"], json={"vendor_ids": invite[1:2], "deadline": deadline})
    check("next round needs the round closed -> 422", early.status_code == 422)
    requests.post(f"{GW}/rfqs/{r2['id']}/close", headers=H["finance"])
    r = requests.post(f"{GW}/rfqs/{r2['id']}/rounds", headers=H["finance"], json={"vendor_ids": [invite[2]], "deadline": deadline})
    check("round 2 for the shortlisted vendor", r.status_code == 200 and r.json()["data"]["round"] == 2 and r.json()["data"]["status"] == "open", r.text[:150])
    out = requests.post(f"{GW}/rfqs/{r2['id']}/responses", headers=H["finance"], json={"vendor_id": invite[1], "total_inr": 1000})
    check("a vendor left off the shortlist can't quote -> 422", out.status_code == 422)
    r = requests.post(f"{GW}/rfqs/{r2['id']}/cancel", headers=H["finance"], json={"reason": "budget moved to Q4"})
    check("cancel with a reason", r.status_code == 200 and r.json()["data"]["status"] == "cancelled")

    step("RFQ recommended above the threshold")
    big = new_request("requester", request_type="hardware", amount=350000, vendor_id=ACME,
                      items=[{"name": "Core switch", "quantity": 1, "unit_price": 350000}]).json()["data"]
    check("₹3.5 L request with no RFQ is flagged", any(f["code"] == "rfq_recommended" for f in big.get("sourcing_flags") or []),
          big.get("sourcing_flags"))
    requests.post(f"{GW}/requests/{big['id']}/reject", headers=H["approver"], json={"comments": "sourcing e2e"})


def receipts():
    step("Partial receipts and the three-way match")
    name = f"Developer laptop E2E {RUN}"
    pr = new_request("requester", request_type="hardware", amount=50000, vendor_id=ACME,
                     items=[{"name": name, "quantity": 50, "unit_price": 1000}]).json()["data"]
    approve_all(pr["id"])
    ordered = sign_contract(pr["id"])
    if not check("approved and signed -> ordered", ordered and ordered["status"] == "ordered", ordered and ordered["status"]):
        return
    rid = pr["id"]
    over = requests.post(f"{GW}/requests/{rid}/receipts", headers=H["requester"], json={"lines": [{"line_no": 0, "quantity": 60}]})
    check("more than ordered -> 409", over.status_code == 409, over.text[:120])
    tags = [f"LT-{RUN}-{n:03d}" for n in range(1, 4)]
    r = requests.post(f"{GW}/requests/{rid}/receipts", headers=H["requester"],
                      json={"lines": [{"line_no": 0, "quantity": 30, "asset_tags": tags}], "notes": "first truck"})
    check("30 of 50 received -> partially_received", r.status_code == 201 and r.json()["data"]["request"]["status"] == "partially_received", r.text[:150])

    def invoice(qty):
        return requests.post(f"{GW}/invoices/match?dry_run=true", headers=H["finance"], json={
            "document_id": str(uuid.uuid4()), "vendor_id": ACME, "total": qty * 1000.0, "po_reference": rid,
            "lines": [{"description": name, "quantity": qty, "unit_price": 1000}]}).json()["data"]
    v = invoice(50)
    check("invoice for 50 with 30 received -> variance", v["status"] == "variance" and any("received" in i for i in v["issues"]),
          f"{v['status']} {v['issues']}")
    m = invoice(30)
    check("invoice for the 30 received -> matches", m["status"] in ("partial", "matched") and m["request_id"] == rid, f"{m['status']} {m['issues']}")
    rec = requests.get(f"{GW}/requests/{rid}/receipts", headers=H["requester"]).json()["data"]
    check("receipts list the asset tags and what's left", rec["lines"][0]["received"] == 30
          and rec["receipts"][0]["lines"][0]["asset_tags"] == tags)
    led = requests.get(f"{GW}/invoices/ledger/{rid}", headers=H["finance"]).json()["data"]
    check("ledger shows received quantity per line", led["lines"][0]["received_quantity"] == 30, led["lines"])
    r = requests.post(f"{GW}/requests/{rid}/receive", headers=H["requester"])
    check("everything else arrived -> fulfilled", r.status_code == 200 and r.json()["data"]["status"] == "fulfilled", r.text[:150])
    m = invoice(50)
    check("now an invoice for all 50 matches", m["status"] == "matched", f"{m['status']} {m['issues']}")


def scorecard():
    step("Vendor scorecard")
    r = requests.get(f"{GW}/vendors/{ACME}/scorecard", headers=H["finance"])
    card = r.json().get("data") or {}
    check("scorecard returned", r.status_code == 200, r.text[:150])
    check("deliveries counted", card.get("deliveries", 0) >= 1 and card.get("on_time_rate") is not None, card)
    check("RFQ response rate after a closed RFQ", card.get("rfq_invitations", 0) >= 1 and card.get("rfq_response_rate") is not None, card)
    check("invoice accuracy is a share or unknown", card.get("invoice_accuracy") is None or 0 <= card["invoice_accuracy"] <= 1)


def main():
    for role in ("requester", "approver", "finance", "admin"):
        H[role] = login(role)
    catalog()
    rfq_flow()
    receipts()
    scorecard()
    step("Rules")
    rules = {x["rule_key"] for g in requests.get(f"{GW}/admin/business-rules", headers=H["admin"]).json()["data"].values() for x in g}
    for key in ("catalog.preapproved_max_inr", "sourcing.rfq_required_above_inr", "sourcing.default_criteria", "invoice.match_against_received"):
        check(f"{key} seeded", key in rules)
    bad = requests.patch(f"{GW}/admin/business-rules/sourcing.default_criteria", headers=H["admin"],
                         json={"new_value": {"price": 0.5}, "justification": "sourcing e2e"})
    check("RFQ weights must add up to 1 -> 400", bad.status_code == 400, str(bad.status_code))

    failed = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("Failed:\n  " + "\n  ".join(failed))
        sys.exit(1)


if __name__ == "__main__":
    main()
