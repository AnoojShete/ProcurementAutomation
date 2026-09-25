"""Full-lifecycle check: one fresh vendor's quote + invoice through all five
agents, verifying every API response along the way — no DB shortcuts.

    auth-service              login / me / refresh / role checks
    document-vendor-agent     ClamAV scan -> parse -> classify -> extract ->
                              vendor match -> invoice->PO match -> confidence
    approval-inventory-agent  spend tier -> inbox -> Temporal approval ->
                              invoice.matched -> invoice_received
    contract-risk-agent       generate -> send -> HMAC webhook -> signed ->
                              risk score
    notification-agent        emails for each step (log + Mailpit)

Needs the stack running (./run.sh). Usage:
    python tests/e2e/invoice_lifecycle.py
Requires: requests, reportlab, pillow.
"""
import hashlib
import hmac
import json
import os
import random
import sys
import time
import uuid
from datetime import date, datetime, timezone

import requests

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "services", "document-vendor-agent", "scripts"))
from synthetic_invoice_lib import build_pdf_bytes, render_document  # noqa: E402

GW = os.getenv("GATEWAY", "http://localhost:8080") + "/api"
MAILPIT = os.getenv("MAILPIT", "http://localhost:8025")
ESIGN_SECRET = os.getenv("ESIGN_WEBHOOK_SECRET", "dev-esign-secret-change-me")
PASSWORD = "DemoPass123!"

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(f"  {'✓' if cond else '✗'} {name}" + (f"  [{detail}]" if detail and not cond else ""))
    return bool(cond)


def step(title):
    print(f"\n── {title}")


def login(role):
    r = requests.post(f"{GW}/auth/login", json={"email": f"{role}@demo.example.com", "password": PASSWORD})
    check(f"login {role} -> 200", r.status_code == 200, r.text[:120])
    return r.json()["data"]


def H(tok):
    return {"Authorization": f"Bearer {tok}"}


def poll(fn, until, timeout=60, interval=1.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = fn()
        if until(last):
            return last
        time.sleep(interval)
    return last


def upload(tok, name, data):
    r = requests.post(f"{GW}/documents/upload", headers=H(tok), files={"file": (name, data, "application/pdf")})
    ok = check(f"upload {name} -> 201", r.status_code == 201, f"{r.status_code} {r.text[:150]}")
    return r.json()["data"]["document_id"] if ok else None


def get_doc(tok, doc_id):
    return requests.get(f"{GW}/documents/{doc_id}", headers=H(tok)).json()["data"]


def main():
    run = uuid.uuid4().hex[:6].upper()
    vendor = {"name": f"Zenith Test Systems {run} Pvt Ltd", "currency": "INR"}
    items = [{"name": "Microsoft 365 E3 Seat License", "quantity": 2, "unit_price": 1650.00}]
    rng = random.Random(run)
    today = date.today()
    quote_lines, quote_total = render_document(rng, "quote", "A", vendor, items, f"QT-{run}", today, "Acme Corp IT Department")
    inv_lines, inv_total = render_document(rng, "invoice", "A", vendor, items, f"INV-{run}", today, "Acme Corp IT Department")
    print(f"Run {run}: vendor '{vendor['name']}', quote/invoice total ₹{inv_total}")

    # ── auth-service ─────────────────────────────────────────────────────
    step("auth-service")
    req_t = login("requester")
    app_t = login("approver")["access_token"]
    fin_t = login("finance")["access_token"]
    adm_t = login("admin")["access_token"]
    me = requests.get(f"{GW}/auth/me", headers=H(req_t["access_token"]))
    check("GET /auth/me -> requester", me.status_code == 200 and me.json()["data"]["role"] == "requester", me.text[:120])
    ref = requests.post(f"{GW}/auth/refresh", json={"refresh_token": req_t["refresh_token"]})
    check("POST /auth/refresh -> new access token", ref.status_code == 200 and ref.json()["data"].get("access_token"), ref.text[:120])
    bad = requests.post(f"{GW}/auth/login", json={"email": "requester@demo.example.com", "password": "wrong"})
    check("wrong password -> 401", bad.status_code == 401, str(bad.status_code))
    check("no token on /requests/ -> 401", requests.get(f"{GW}/requests/").status_code == 401)
    rt = req_t["access_token"]

    # ── document-vendor-agent: quote ─────────────────────────────────────
    step("document-vendor-agent — supporting quote")
    eicar = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
    r = requests.post(f"{GW}/documents/upload", headers=H(rt), files={"file": ("eicar.pdf", eicar, "application/pdf")})
    check("ClamAV rejects EICAR -> 422", r.status_code == 422, f"{r.status_code} {r.text[:120]}")
    quote_id = upload(rt, f"quote_{run}.pdf", build_pdf_bytes(quote_lines))
    q = poll(lambda: get_doc(rt, quote_id), lambda d: d["status"] not in ("pending", "processing"), timeout=120)
    check("quote processed -> classified", q["status"] == "classified", q["status"])
    check("quote classified as 'quote'", q["document_type"] == "quote", q["document_type"])
    qf = q.get("extracted_fields") or {}
    check("quote total extracted", abs(float(qf.get("total") or 0) - quote_total) < 0.01, f"{qf.get('total')} vs {quote_total}")
    vendor_id = q.get("vendor_id")
    check("vendor matched/created", bool(vendor_id))
    v = requests.get(f"{GW}/vendors/", headers=H(adm_t)).json()["data"]
    check("new vendor listed in /vendors", any(x["id"] == vendor_id for x in v))

    # ── approval-inventory-agent ─────────────────────────────────────────
    step("approval-inventory-agent — request + approval")
    r = requests.post(f"{GW}/requests/", headers=H(rt), json={
        "request_type": "license", "department": "Engineering", "amount": inv_total, "currency": "INR",
        "vendor_id": vendor_id, "items": [{"description": items[0]["name"], "quantity": 2, "unit_price": 1650.0}],
        "requested_by": "spoofed@evil.com",
    })
    check("create request -> 200", r.status_code == 200, r.text[:150])
    pr = r.json()["data"]
    pr_id = pr["id"]
    check("requested_by from JWT (not body)", pr["requested_by"] == "requester@demo.example.com", pr["requested_by"])
    check("manager tier chain = [dept_manager]", pr["approval_chain"] == ["dept_manager"], pr["approval_chain"])
    check("status pending_approval", pr["status"] == "pending_approval", pr["status"])
    inbox = poll(lambda: requests.get(f"{GW}/inbox/dept_manager", headers=H(app_t)).json()["data"],
                 lambda d: any(i["request_id"] == pr_id for i in d), timeout=15)
    check("request in dept_manager inbox", any(i["request_id"] == pr_id for i in inbox))
    r = requests.post(f"{GW}/requests/{pr_id}/approve", headers=H(rt), json={})
    check("requester cannot approve -> 403", r.status_code == 403, str(r.status_code))
    r = requests.post(f"{GW}/requests/{pr_id}/approve", headers=H(app_t), json={"comments": "lifecycle test"})
    check("approver approves -> 200", r.status_code == 200, r.text[:150])
    pr = poll(lambda: requests.get(f"{GW}/requests/{pr_id}", headers=H(app_t)).json()["data"],
              lambda d: d["status"] == "approved", timeout=30)
    check("Temporal workflow -> approved", pr["status"] == "approved", pr["status"])
    hist = pr.get("history") or pr.get("approval_history") or []
    check("decision recorded as approver's email", any(h.get("decided_by") == "approver@demo.example.com" for h in hist), hist)

    # ── document-vendor-agent: invoice -> PO match ───────────────────────
    step("document-vendor-agent — invoice + 3-way match")
    inv_id = upload(rt, f"invoice_{run}.pdf", build_pdf_bytes(inv_lines))
    d = poll(lambda: get_doc(rt, inv_id), lambda x: x["status"] not in ("pending", "processing"), timeout=120)
    check("invoice processed -> classified", d["status"] == "classified", d["status"])
    check("invoice classified as 'invoice'", d["document_type"] == "invoice", d["document_type"])
    check("invoice matched to same vendor", d.get("vendor_id") == vendor_id, f"{d.get('vendor_id')} vs {vendor_id}")
    ext = d.get("extracted_fields") or {}
    check("invoice matched to the purchase request", ext.get("matched_po_id") == pr_id,
          f"matched_po_id={ext.get('matched_po_id')} unmatched={ext.get('unmatched_invoice')} candidates={ext.get('candidate_pos')}")
    check("not flagged duplicate", not d.get("is_likely_duplicate"))
    cc = ext.get("crosscheck") or {}
    check("LayoutLMv3 cross-check ran", cc.get("available") is True,
          f"{cc.get('agreement_rate_note')} (run scripts/download-models.sh once)")
    pr = poll(lambda: requests.get(f"{GW}/requests/{pr_id}", headers=H(app_t)).json()["data"],
              lambda x: x["status"] == "invoice_received", timeout=20)
    check("invoice.matched -> request invoice_received", pr["status"] == "invoice_received", pr["status"])

    # ── contract-risk-agent ──────────────────────────────────────────────
    step("contract-risk-agent — contract, e-sign, risk")
    r = requests.post(f"{GW}/contracts/generate", headers=H(adm_t),
                      json={"purchase_request_id": pr_id, "template_name": "saas_subscription"})
    check("generate contract -> 200/201", r.status_code in (200, 201), r.text[:200])
    c = r.json().get("data") or {}
    cid = c.get("id")
    check("contract linked to request + vendor", c.get("purchase_request_id") == pr_id and c.get("vendor_id") == vendor_id,
          f"pr={c.get('purchase_request_id')} vendor={c.get('vendor_id')}")
    if cid:
        r = requests.post(f"{GW}/contracts/{cid}/send-for-signature", headers=H(adm_t), json={"provider": "documenso"})
        check("send for signature -> pending_signature", r.status_code == 200 and r.json()["data"]["status"] == "pending_signature", r.text[:150])
        body = {"provider_event_id": f"evt-{run}", "contract_id": cid, "signed_by": "vendor@zenith.example",
                "signed_at": datetime.now(timezone.utc).isoformat()}
        bad_sig = requests.post(f"{GW}/webhooks/esign", json=dict(body, signature="0" * 64))
        check("webhook with bad signature -> 401", bad_sig.status_code == 401, str(bad_sig.status_code))
        sig = hmac.new(ESIGN_SECRET.encode(), json.dumps(body, sort_keys=True, separators=(",", ":")).encode(), hashlib.sha256).hexdigest()
        r = requests.post(f"{GW}/webhooks/esign", json=dict(body, signature=sig))
        check("signed webhook -> 200", r.status_code == 200, r.text[:150])
        r2 = requests.post(f"{GW}/webhooks/esign", json=dict(body, signature=sig))
        check("replayed webhook is a no-op 2xx", r2.status_code in (200, 202), f"{r2.status_code} {r2.text[:100]}")
        c = requests.get(f"{GW}/contracts/{cid}", headers=H(adm_t)).json()["data"]
        check("contract status signed", c["status"] == "signed", c["status"])
        pr = poll(lambda: requests.get(f"{GW}/requests/{pr_id}", headers=H(app_t)).json()["data"],
                  lambda x: x["status"] == "fulfilled", timeout=20)
        check("contract.signed -> request fulfilled", pr["status"] == "fulfilled", pr["status"])
    r = requests.post(f"{GW}/vendors/{vendor_id}/risk/recompute", headers=H(fin_t))
    check("finance recomputes vendor risk -> 200", r.status_code == 200, r.text[:150])
    risk = requests.get(f"{GW}/vendors/{vendor_id}/risk", headers=H(adm_t)).json().get("data") or {}
    check("risk band + top factors present", risk.get("risk_band") in ("Low", "Medium", "High") and risk.get("top_factors"), risk)
    spend = requests.get(f"{GW}/vendors/{vendor_id}/spend-summary", headers=H(adm_t))
    check("vendor spend-summary -> 200", spend.status_code == 200, spend.text[:120])

    # ── notification-agent ───────────────────────────────────────────────
    step("notification-agent")
    want = {"approval.requested", "approval.decided", "contract.generated", "contract.signed", "risk.score.updated", "document.classified"}
    def seen():
        log = requests.get(f"{GW}/notifications/log?limit=200", headers=H(adm_t)).json()["data"]
        mine = [n for n in log if pr_id in json.dumps(n) or vendor_id in json.dumps(n) or (cid and cid in json.dumps(n))
                or inv_id in json.dumps(n) or quote_id in json.dumps(n)]
        return {n["event_type"] for n in mine}
    got = poll(seen, lambda s: want <= s, timeout=30, interval=2)
    for ev in sorted(want):
        check(f"notification for {ev}", ev in got, f"got {sorted(got)}")
    mp = requests.get(f"{MAILPIT}/api/v1/messages?limit=50").json()
    check("Mailpit has emails", mp.get("total", 0) > 0)

    # ── cross-cutting ────────────────────────────────────────────────────
    step("audit + admin")
    for svc, path in [("requests", f"requests/audit?entity_id={pr_id}"), ("documents", f"documents/audit?entity_id={inv_id}"),
                      ("contracts", f"contracts/audit?entity_id={cid}")]:
        r = requests.get(f"{GW}/{path}", headers=H(adm_t))
        check(f"{svc} audit trail has entries", r.status_code == 200 and len(r.json()["data"]) > 0, f"{r.status_code} {r.text[:120]}")
    rl = requests.get(f"{GW}/admin/model-routing-log?limit=100", headers=H(adm_t)).json()["data"]
    check("model routing logged for invoice", any(x["document_id"] == inv_id for x in rl))
    check("routing confidence is numeric", all(isinstance(x["confidence"], (int, float, type(None))) for x in rl))
    check("requester blocked from audit -> 403", requests.get(f"{GW}/requests/audit", headers=H(rt)).status_code == 403)

    passed = sum(ok for _, ok in results)
    print(f"\n{'=' * 66}\n  invoice lifecycle: {passed} passed, {len(results) - passed} failed\n{'=' * 66}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
