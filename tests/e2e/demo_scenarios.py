"""Demo script (FR-05): five scenarios a reviewer can run by hand from a
fresh stack, and this script runs them for real first.

Each step says what to do in the app, which agent acts and which event it
sends, and what you should see. The script performs the same step through
the gateway (as the same role), checks that you would see exactly that,
and takes a screenshot of the page. It then writes docs/demo-script.html
from the same step list — so the written script can't drift from what the
app does, and a broken pipeline shows up as a red row.

    ./run.sh && ./scripts/seed-demo-data.sh
    pip install -r tests/e2e/requirements.txt playwright
    python tests/e2e/demo_scenarios.py              # all five (~4 min)
    python tests/e2e/demo_scenarios.py 2 3          # some
    python tests/e2e/demo_scenarios.py --no-screens # checks + HTML only

Every run uses new vendor names, so it works on any data and can be
repeated. Scenario 3 continues scenario 2's order, and 5 continues 4's
vendor. CHROMIUM_PATH points at an existing Chromium.
"""
import asyncio
import html
import os
import random
import shutil
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable, Optional

import requests

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "services", "document-vendor-agent", "scripts"))
from synthetic_invoice_lib import build_pdf_bytes, render_document  # noqa: E402

BASE = os.getenv("GATEWAY", "http://localhost:8080")
GW = BASE + "/api"
PASSWORD = "DemoPass123!"
DEMO_VENDOR = "11111111-1111-1111-1111-111111111111"   # Acme IT Supplies Inc (seed-demo-data.sh)
SHOTS = os.path.join(ROOT, "docs", "demo")
HTML_OUT = os.path.join(ROOT, "docs", "demo-script.html")
INBOX = os.path.join(ROOT, "inbox")


# ── helpers ────────────────────────────────────────────────────────────────

class StepFailed(Exception):
    pass


def expect(cond, detail):
    if not cond:
        raise StepFailed(str(detail)[:300])


def H(tok):
    return {"Authorization": f"Bearer {tok}"}


def poll(fn, until, timeout=90, interval=2.0):
    end, last = time.time() + timeout, None
    while time.time() < end:
        try:
            last = fn()
            if until(last):
                return last
        except requests.RequestException:
            pass
        time.sleep(interval)
    return last


class Ctx(dict):
    """Shared state: tokens, ids created by earlier steps."""

    def tok(self, role):
        if role not in self:
            r = requests.post(f"{GW}/auth/login", json={"email": f"{role}@demo.example.com", "password": PASSWORD}, timeout=30)
            expect(r.status_code == 200, f"login {role}: {r.status_code} — run ./scripts/seed-demo-data.sh")
            self[role] = r.json()["data"]["access_token"]
        return self[role]

    def api_get(self, role, path, **kw):
        return requests.get(f"{GW}{path}", headers=H(self.tok(role)), timeout=30, **kw)

    def api_post(self, role, path, **kw):
        return requests.post(f"{GW}{path}", headers=H(self.tok(role)), timeout=60, **kw)


def request_of(c, pr_id):
    return c.api_get("admin", f"/requests/{pr_id}").json()["data"]


def contract_for(c, pr_id):
    return next((x for x in c.api_get("admin", "/contracts/?limit=100").json()["data"] if x["purchase_request_id"] == pr_id), None)


def doc_of(c, doc_id):
    return c.api_get("admin", f"/documents/{doc_id}").json()["data"]


def upload(c, role, name, data):
    r = c.api_post(role, "/documents/upload", files={"file": (name, data, "application/pdf")})
    expect(r.status_code == 201, f"upload: {r.status_code} {r.text[:150]}")
    return r.json()["data"]["document_id"]


def sign(c, cid, acknowledge):
    return c.api_post("finance", f"/contracts/{cid}/sign", json={
        "signer_name": "Farah Finance", "signer_designation": "Finance Head", "legal_consent": True,
        "risk_acknowledged": acknowledge})


def doc_pdf(c, kind, vendor, items, number, po_ref=None):
    lines, total = render_document(random.Random(number), kind, "A", {"name": vendor, "currency": "INR"}, items,
                                   number, date.today(), "Acme Corp IT Department")
    if po_ref:
        at = next(i for i, l in enumerate(lines) if l.startswith("Bill To"))
        lines.insert(at + 1, f"PO Reference: {po_ref}")
    return build_pdf_bytes(lines), total


def brand(rng) -> str:
    """A made-up, pronounceable company word, different every run — so a
    repeat run isn't (rightly) flagged as a look-alike or duplicate of the
    last one."""
    cons, vow = "bdfgklmnprstvz", "aeiou"
    return "".join(rng.choice(cons) + rng.choice(vow) for _ in range(3)).capitalize() + rng.choice(["x", "n", "r", "l"])


# ── scenario model ─────────────────────────────────────────────────────────

@dataclass
class Step:
    do: str                      # what the presenter does in the app
    agent: str                   # which agent acts
    event: str                   # Kafka event(s), or "—"
    see: str                     # what you should see
    run: Callable[[Ctx], Optional[str]]   # performs + checks; returns a short note
    shot: Optional[tuple] = None  # (role, lambda ctx: path, optional "text to scroll to")
    result: str = "not run"
    note: str = ""
    image: Optional[str] = None


@dataclass
class Scenario:
    num: int
    title: str
    proves: str
    roles: str
    minutes: int
    steps: list = field(default_factory=list)


S: list[Scenario] = []


def scenario(num, title, proves, roles, minutes):
    sc = Scenario(num, title, proves, roles, minutes)
    S.append(sc)
    return sc


# ── 1. In-app request → delivery ───────────────────────────────────────────

s1 = scenario(1, "In-app request to delivery", "One request passes every agent: approval by spend tier, a contract generated and sent with no clicks, an in-app signature, then delivery.",
              "requester → approver → finance → requester", 5)


def s1_create(c):
    r = c.api_post("requester", "/requests/", json={
        "request_type": "license", "department": "Design", "amount": 2500, "currency": "INR", "vendor_id": DEMO_VENDOR,
        "items": [{"description": "Figma Professional seat", "quantity": 1, "unit_price": 2500}],
        "comments": f"Demo scenario 1 ({c['run']})"})
    expect(r.status_code == 200, r.text[:200])
    pr = r.json()["data"]
    c["s1_pr"] = pr["id"]
    expect(pr["status"] == "pending_approval" and pr["approval_chain"] == ["dept_manager"], f"{pr['status']} {pr['approval_chain']}")
    return f"PR-{pr['id'][:8]} · pending_approval · chain dept_manager"


def s1_approve(c):
    inbox = poll(lambda: c.api_get("approver", "/inbox/dept_manager").json()["data"],
                 lambda d: any(i["request_id"] == c["s1_pr"] for i in d), timeout=30)
    expect(any(i["request_id"] == c["s1_pr"] for i in inbox or []), "not in the approver's queue")
    r = c.api_post("requester", f"/requests/{c['s1_pr']}/approve", json={})
    expect(r.status_code == 403, f"requester could approve: {r.status_code}")
    r = c.api_post("approver", f"/requests/{c['s1_pr']}/approve", json={"comments": "Within budget"})
    expect(r.status_code == 200, r.text[:200])
    pr = poll(lambda: request_of(c, c["s1_pr"]), lambda d: d["status"] == "approved", timeout=30)
    expect(pr["status"] == "approved", pr["status"])
    return "requester's own approve → 403; approver → approved"


def s1_contract(c):
    ct = poll(lambda: contract_for(c, c["s1_pr"]), lambda x: x and x["status"] == "pending_signature", timeout=60)
    expect(ct and ct["status"] == "pending_signature",
           f"contract is {ct and ct['status'] or 'missing'}, expected pending_signature — "
           "check rule contract.auto_send_scope (should be 'all') and contract-risk-agent's logs")
    c["s1_contract"] = ct["id"]
    d = c.api_get("admin", f"/contracts/{ct['id']}").json()["data"]
    expect(d.get("sent_automatically") is True, "not marked as sent automatically")
    return f"contract {ct['id'][:8]} · pending_signature · sent automatically"


def s1_sign(c):
    # Deterministic scorecard: a vendor whose checks can't all be run here
    # (no external registries in the demo) is provisional, so signing asks
    # for an acknowledgement; a fully assessed Low/Medium vendor signs directly.
    r = sign(c, c["s1_contract"], acknowledge=False)
    acknowledged = r.status_code == 409 and "risk_acknowledgement_required" in r.text
    if acknowledged:
        r = sign(c, c["s1_contract"], acknowledge=True)
    expect(r.status_code == 200, f"{r.status_code} {r.text[:200]}")
    pr = poll(lambda: request_of(c, c["s1_pr"]), lambda d: d["status"] == "ordered", timeout=30)
    expect(pr["status"] == "ordered", pr["status"])
    cert = c.api_get("finance", f"/contracts/{c['s1_contract']}/signature-certificate").json()["data"]
    expect(cert, "no certificate")
    return ("signed after acknowledging the vendor's incomplete risk checks" if acknowledged
            else "signed (vendor cleared: no acknowledgement needed)") + " · request ordered · certificate issued"


def s1_receive(c):
    r = c.api_post("requester", f"/requests/{c['s1_pr']}/receive")
    expect(r.status_code == 200 and r.json()["data"]["status"] == "fulfilled", f"{r.status_code} {r.text[:150]}")
    return "fulfilled"


s1.steps = [
    Step("As <b>requester</b>: New Request → licence, vendor <i>Acme IT Supplies Inc</i>, 1 × Figma Professional seat at ₹2,500 → Submit.",
         "Approval & Inventory", "approval.requested",
         "The request page shows <b>Pending approval</b>; the chain is one step (department manager) because ₹2,500 is in the ₹500–5,000 tier.",
         s1_create, ("requester", lambda c: f"/app/requests/{c['s1_pr']}")),
    Step("As <b>approver</b>: Approval Queue → open the request → Approve. (Optionally first try Approve as the requester: refused.)",
         "Approval & Inventory (Temporal workflow)", "approval.decided",
         "Status flips to <b>Approved</b> a moment later; the requester can't approve their own request.",
         s1_approve, ("approver", lambda c: f"/app/requests/{c['s1_pr']}")),
    Step("Nothing — wait ~5 s, then open Contracts.",
         "Contract & Risk", "contract.generated",
         "A contract for this request, <b>Pending signature</b>, marked as sent automatically; clauses read by Legal-BERT.",
         s1_contract, ("finance", lambda c: f"/app/contracts/{c['s1_contract']}", "text=Vendor risk")),
    Step("As <b>finance</b>: open the contract → Sign now → type a name, tick consent → Sign.",
         "Contract & Risk → Approval & Inventory", "contract.signed",
         "Contract <b>Signed</b> with a signature certificate; the request moves to <b>Ordered</b>. (The vendor's risk checks are incomplete in the demo, so the signer ticks the risk acknowledgement; a fully assessed Low/Medium vendor signs without it.)",
         s1_sign, ("finance", lambda c: f"/app/contracts/{c['s1_contract']}")),
    Step("As <b>requester</b>: open the request → Mark as received.",
         "Approval & Inventory", "—",
         "Status <b>Fulfilled</b>; every lifecycle step is now ticked.",
         s1_receive, ("requester", lambda c: f"/app/requests/{c['s1_pr']}")),
]


# ── 2. Drop-folder quote → contract, unattended ────────────────────────────

s2 = scenario(2, "A quote dropped in a folder, to a signed contract", "Documents arriving without anyone clicking run through every agent: scan, read, vendor, request, approval, contract.",
              "nobody, then finance to sign", 4)


def s2_drop(c):
    c["s2_vendor"] = f"{brand(c['rng'])} {brand(c['rng'])} Pvt Ltd"
    c["s2_items"] = [{"name": "Wireless keyboard", "quantity": 2, "unit_price": float(c["rng"].randint(150, 200))}]
    pdf, total = doc_pdf(c, "quote", c["s2_vendor"], c["s2_items"], f"QT-{c['run']}")
    c["s2_total"] = total
    os.makedirs(INBOX, exist_ok=True)
    name = f"quote_{c['run']}.pdf"
    with open(os.path.join(INBOX, name + ".part"), "wb") as f:
        f.write(pdf)
    os.replace(os.path.join(INBOX, name + ".part"), os.path.join(INBOX, name))
    c["s2_file"] = name
    doc = poll(lambda: next((d for d in c.api_get("admin", "/documents/?limit=30").json()["data"]
                             if d.get("original_filename") == name and d["status"] not in ("pending", "processing")), None),
               lambda d: d is not None, timeout=150, interval=3)
    expect(doc, "file not picked up / not processed within 150 s (is the worker running? ./inbox mounted?)")
    c["s2_doc"] = doc["id"]
    expect(doc["status"] == "classified" and doc["document_type"] == "quote", f"{doc['status']} {doc['document_type']}")
    return f"₹{total:,.2f} quote · classified as quote · uploader inbox@procurement.local"


def s2_request(c):
    note = ""
    d = doc_of(c, c["s2_doc"])
    if d.get("needs_review"):
        # The presenter's branch: finance opens the document, checks the
        # total and clicks "Confirm as Correct" (the same call the page makes).
        cc = (d.get("extracted_fields") or {}).get("crosscheck") or {}
        why = (f"LayoutLMv3 read total {cc['layoutlm_fields'].get('total')} vs {cc['docling_fields'].get('total')}"
               if cc.get("disagrees") else "low confidence")
        r = c.api_post("finance", f"/documents/{c['s2_doc']}/review", json={
            "vendor_name": d.get("vendor_name") or c["s2_vendor"], "document_type": "quote",
            "extracted_fields": d.get("extracted_fields") or {}})
        expect(r.status_code == 200, f"review: {r.status_code} {r.text[:200]}")
        note = f"went to review ({why}) → finance confirmed → "
    pr = poll(lambda: next((r for r in c.api_get("admin", "/requests/?limit=50").json()["data"]
                            if r.get("document_id") == c["s2_doc"]), None), lambda r: r is not None, timeout=60)
    expect(pr, "no purchase request created from the quote (did it need review?)")
    c["s2_pr"] = pr["id"]
    pr = poll(lambda: request_of(c, c["s2_pr"]), lambda d: d["status"] != "pending_approval", timeout=30)
    expect(pr["status"] in ("approved", "ordered"), pr["status"])
    return note + f"PR-{pr['id'][:8]} · auto-approved (≤ ₹500 tier)"


def s2_contract(c):
    ct = poll(lambda: contract_for(c, c["s2_pr"]), lambda x: x and x["status"] == "pending_signature", timeout=60)
    expect(ct and ct["status"] == "pending_signature",
           f"contract is {ct and ct['status'] or 'missing'}, expected pending_signature — check contract-risk-agent's logs")
    c["s2_contract"] = ct["id"]
    return "contract sent for signature automatically"


def s2_sign(c):
    r = sign(c, c["s2_contract"], acknowledge=False)
    if r.status_code == 409:
        r = sign(c, c["s2_contract"], acknowledge=True)
        note = "vendor High → acknowledgement asked, given"
    else:
        note = "signed"
    expect(r.status_code == 200, f"{r.status_code} {r.text[:200]}")
    pr = poll(lambda: request_of(c, c["s2_pr"]), lambda d: d["status"] == "ordered", timeout=30)
    expect(pr["status"] == "ordered", pr["status"])
    return note + " · request ordered"


s2.steps = [
    Step("Copy a vendor quote into <code>./inbox</code> (here: a quote under ₹500 from a vendor the system has never seen). Watch Control Panel → Dropped files.",
         "Document & Vendor (inbox watcher, worker pipeline)", "document.ingested → document.classified, vendor.matched",
         "Within ~30 s the file is scanned, stored, read and classified as a <b>quote</b>; a new vendor is created from it.",
         s2_drop, ("admin", lambda c: f"/app/documents/{c['s2_doc']}", "text=Extracted Fields")),
    Step("Usually nothing. If the document says <b>Needs review</b> (most often the LayoutLMv3 cross-check read the subtotal as the total), as <b>finance</b> open it, check the total against the PDF and click <b>Confirm as Correct</b>.",
         "Approval & Inventory", "approval.requested, approval.decided",
         "A purchase request created from the quote and <b>auto-approved</b> (under ₹500) — straight away, or right after the confirmation; a quote that needs review never becomes a request on its own.",
         s2_request, ("admin", lambda c: f"/app/requests/{c['s2_pr']}")),
    Step("Nothing.", "Contract & Risk", "contract.generated",
         "A contract, <b>Pending signature</b> — Control Panel → Dropped files links document, request and contract.",
         s2_contract, ("admin", lambda c: "/app/control-panel", "text=Dropped files")),
    Step("As <b>finance</b>: open the contract → Sign now. (The new vendor was scored and screened when the contract was made; if it came out High, tick the risk acknowledgement.)",
         "Contract & Risk → Approval & Inventory", "contract.signed",
         "Contract <b>Signed</b>, request <b>Ordered</b> — from a dropped file with one human action.",
         s2_sign, ("finance", lambda c: f"/app/contracts/{c['s2_contract']}")),
]


# ── 3. Invoice: mismatch held, match booked ────────────────────────────────

s3 = scenario(3, "Invoice matching: an overcharge is held, the right invoice is booked", "Three-way match line by line against the order: a unit price above tolerance never goes through silently.",
              "finance", 3)


def s3_mismatch(c):
    po_ref = f"PO-{c['s2_pr'][:8].upper()}"
    items = [dict(i, unit_price=round(i["unit_price"] * 1.10, 2)) for i in c["s2_items"]]
    pdf, total = doc_pdf(c, "invoice", c["s2_vendor"], items, f"INV-{c['run']}-X", po_ref)
    doc_id = upload(c, "finance", f"invoice_overcharged_{c['run']}.pdf", pdf)
    c["s3_bad"] = doc_id
    d = poll(lambda: doc_of(c, doc_id), lambda x: x["status"] not in ("pending", "processing"), timeout=120)
    ext = d.get("extracted_fields") or {}
    expect(d["document_type"] == "invoice", d["document_type"])
    expect(ext.get("matched_po_id") != c["s2_pr"], f"overcharged invoice was matched: {ext.get('matched_po_id')}")
    expect(d.get("needs_review"), "overcharged invoice did not go to review")
    m = ext.get("invoice_match") or {}
    expect(m.get("status") == "variance" and m.get("purchase_request_id") == c["s2_pr"]
           and any("unit price" in i for i in m.get("issues", [])), f"not held for the price: {m}")
    c["s3_issue"] = next(i for i in m["issues"] if "unit price" in i)
    pr = request_of(c, c["s2_pr"])
    expect(pr["status"] == "ordered", f"request moved to {pr['status']}")
    return f"₹{total:,.2f} · variance: {c['s3_issue']} · needs review · request still ordered"


def s3_match(c):
    po_ref = f"PO-{c['s2_pr'][:8].upper()}"
    pdf, total = doc_pdf(c, "invoice", c["s2_vendor"], c["s2_items"], f"INV-{c['run']}", po_ref)
    doc_id = upload(c, "finance", f"invoice_{c['run']}.pdf", pdf)
    c["s3_good"] = doc_id
    d = poll(lambda: doc_of(c, doc_id), lambda x: x["status"] not in ("pending", "processing"), timeout=120)
    ext = d.get("extracted_fields") or {}
    expect(ext.get("matched_po_id") == c["s2_pr"], f"matched {ext.get('matched_po_id')}, candidates {ext.get('candidate_pos')}")
    pr = poll(lambda: request_of(c, c["s2_pr"]), lambda x: x["status"] == "invoice_received", timeout=30)
    expect(pr["status"] == "invoice_received", pr["status"])
    ledger = c.api_get("finance", f"/invoices/ledger/{c['s2_pr']}").json().get("data") or {}
    expect(ledger.get("remaining_amount", 1) <= 0.01, ledger)
    return f"₹{total:,.2f} · matched to PR-{c['s2_pr'][:8]} · request invoice_received · nothing left to invoice"


s3.steps = [
    Step("As <b>finance</b>: Documents → Upload an invoice from the scenario-2 vendor that quotes the PO number but charges 10 % more per item.",
         "Document & Vendor → Approval & Inventory (invoice ledger)", "document.classified",
         "The invoice is read and linked to the order, but flagged as a <b>variance</b> (“unit price … is above the agreed …”): it goes to <b>Needs review</b>, nothing is booked, and the request stays <b>Ordered</b>.",
         s3_mismatch, ("finance", lambda c: f"/app/documents/{c['s3_bad']}")),
    Step("Upload the correct invoice (same PO, agreed prices).",
         "Document & Vendor → Approval & Inventory", "invoice.matched",
         "Matched line by line to the request; the request moves to <b>Invoice received</b> with nothing left to invoice.",
         s3_match, ("finance", lambda c: f"/app/requests/{c['s2_pr']}")),
]


# ── 4. New vendor: onboarding checks, risk before signing ──────────────────

s4 = scenario(4, "A new vendor: onboarding checks and risk before signing", "Vendor data is checked before it's trusted, every vendor is scored and screened before its first contract, and nobody signs with a High-risk vendor without acknowledging it.",
              "finance → requester → approver → finance", 5)


def s4_checks(c):
    r = c.api_post("finance", "/vendors/onboard/validate", json={"name": "Acme IT Suplies Inc", "gstin": "27AAPFU0939F1ZX"})
    expect(r.status_code == 200, r.text[:200])
    d = r.json()["data"]
    fields = {e["field"] for e in d["errors"]}
    expect(not d["ok"] and fields >= {"gstin", "name"}, f"expected GSTIN + duplicate errors: {d['errors']}")
    r = c.api_post("finance", "/vendors/onboard/validate", json={"name": "Acme IT Supply Co"})
    d = r.json()["data"]
    expect("lookalike" in d.get("needs_confirmation", []), f"no look-alike warning: {d}")
    return "typo'd name → duplicate refused · bad GSTIN check digit refused · similar name → look-alike to confirm"


def s4_onboard(c):
    c["s4_vendor_name"] = f"{brand(c['rng'])} {brand(c['rng'])} LLC"
    r = c.api_post("finance", "/vendors/onboard", json={
        "name": c["s4_vendor_name"], "country": "US", "contact_email": "billing@northwind.example", "category": "Software",
        "bank_account_number": "50100" + c["run_digits"], "routing_code": "HDFC0001234",
        "payment_beneficiary_name": c["s4_vendor_name"],
        "confirm": ["no_gstin"], "no_gstin_reason": "Foreign vendor (US), not registered for GST in India"})
    expect(r.status_code == 201, f"{r.status_code} {r.text[:250]}")
    c["s4_vendor"] = r.json()["data"]["id"] if "id" in r.json()["data"] else r.json()["data"]["vendor"]["id"]
    return "onboarded without GSTIN (reason given) · bank details pending a second person"


def s4_signals(c):
    # Deterministic risk scorecard: recompute, then read the summary.
    r = c.api_post("finance", f"/vendors/{c['s4_vendor']}/risk/recompute", json={})
    expect(r.status_code in (200, 202), f"{r.status_code} {r.text[:200]}")
    risk = poll(lambda: c.api_get("finance", f"/vendors/{c['s4_vendor']}/risk"), lambda x: x.status_code == 200, timeout=60).json()["data"]
    clearance = c.api_get("finance", f"/vendors/{c['s4_vendor']}/clearance?purpose=contract&spend_amount=4200").json()["data"]
    expect(clearance.get("cleared") is False, f"a new foreign vendor with checks missing was cleared: {clearance}")
    scr = c.api_get("finance", f"/vendors/{c['s4_vendor']}/sanctions").json()["data"]
    screened = (scr.get("latest") or {}).get("status")
    expect(not scr["list"].get("available") or screened in ("clear", "potential_match", "cleared"), f"not screened: {scr}")
    return (f"scored {risk.get('total_points')} points · {risk.get('final_band')} · {risk.get('rating_status')} · not cleared"
            + (f" · sanctions screening: {screened}" if screened else " · no sanctions list downloaded"))


def s4_request(c):
    r = c.api_post("requester", "/requests/", json={
        "request_type": "saas", "department": "Data", "amount": 4200, "currency": "INR", "vendor_id": c["s4_vendor"],
        "items": [{"description": "Analytics workspace, 3 months", "quantity": 1, "unit_price": 4200}],
        "comments": f"Demo scenario 4 ({c['run']})"})
    expect(r.status_code == 200, r.text[:200])
    c["s4_pr"] = r.json()["data"]["id"]
    r = c.api_post("approver", f"/requests/{c['s4_pr']}/approve", json={"comments": "OK"})
    expect(r.status_code == 200, r.text[:200])
    ct = poll(lambda: contract_for(c, c["s4_pr"]), lambda x: x and x["status"] == "pending_signature", timeout=60)
    expect(ct, "no contract sent")
    c["s4_contract"] = ct["id"]
    risk = c.api_get("finance", f"/contracts/{ct['id']}").json()["data"].get("vendor_risk") or {}
    expect(risk.get("acknowledgement_required") is True, f"risk panel doesn't ask for acknowledgement: {risk}")
    return f"approved → contract {ct['id'][:8]} pending signature · risk panel: “{risk.get('acknowledgement_reason')}”"


def s4_sign(c):
    r = sign(c, c["s4_contract"], acknowledge=False)
    expect(r.status_code == 409 and "risk_acknowledgement_required" in r.text, f"signed without acknowledgement: {r.status_code}")
    r = sign(c, c["s4_contract"], acknowledge=True)
    expect(r.status_code == 200, f"{r.status_code} {r.text[:200]}")
    cert = c.api_get("finance", f"/contracts/{c['s4_contract']}/signature-certificate").json()["data"]
    at = cert.get("vendor_risk_at_signing") or {}
    expect(at.get("acknowledged") is True, f"certificate: {at}")
    return f"without acknowledgement → refused (409); with it → signed; certificate records {at.get('risk_band')} + acknowledged"


s4.steps = [
    Step("As <b>finance</b>: Vendors → Onboard vendor → name <i>Acme IT Suplies Inc</i>, GSTIN <code>27AAPFU0939F1ZX</code> → Check profile. Then change the name to <i>Acme IT Supply Co</i> and clear the GSTIN → Check profile.",
         "Document & Vendor", "—",
         "First: <b>duplicate of “Acme IT Supplies Inc”</b> and <b>GSTIN failed check-digit validation</b> — Onboard stays disabled. Then: a <b>look-alike</b> warning (87 % similar) and a no-GSTIN warning, each to be confirmed with a reason.",
         s4_checks, None),
    Step("Onboard a real new vendor without a GSTIN (give the reason) and with bank details.",
         "Document & Vendor", "vendor.payment_details_flagged",
         "The vendor exists; its bank details are <b>pending verification</b> by a second person (scenario 5).",
         s4_onboard, ("finance", lambda c: f"/app/vendors/{c['s4_vendor']}")),
    Step("Still as <b>finance</b>, on the vendor page → Full risk scorecard → Recompute Rating.",
         "Contract & Risk", "risk.score.updated",
         "The deterministic scorecard lists each check with its points and source; a new foreign vendor with most checks not yet assessed is <b>provisional</b> and <b>not cleared</b>. It has also been screened against the sanctions list (<i>Clear</i>).",
         s4_signals, ("finance", lambda c: f"/app/vendors/{c['s4_vendor']}/risk", "text=Recompute Rating")),
    Step("As <b>requester</b>: a ₹4,200 SaaS request for that vendor; as <b>approver</b>: approve it.",
         "Approval & Inventory → Contract & Risk", "approval.requested, approval.decided, contract.generated",
         "A contract, <b>Pending signature</b>, whose Vendor risk panel shows the vendor isn't cleared and says signing needs an acknowledgement.",
         s4_request, ("finance", lambda c: f"/app/contracts/{c['s4_contract']}", "text=Vendor risk")),
    Step("As <b>finance</b>: Sign now — first without ticking the risk acknowledgement, then with it.",
         "Contract & Risk", "contract.signed",
         "Sign stays <b>disabled</b> until the risk is acknowledged; the signature certificate records the band and the acknowledgement.",
         s4_sign, ("finance", lambda c: f"/app/contracts/{c['s4_contract']}")),
]


# ── 5. Bank-detail change: dual control ────────────────────────────────────

s5 = scenario(5, "Bank details need a second person", "Changed or new bank details — the most common invoice fraud — can't be used until someone else confirms them.",
              "finance → admin", 2)


def s5_self(c):
    ch = c.api_get("finance", f"/vendors/{c['s4_vendor']}/payment-changes").json()["data"]
    pending = [x for x in ch if x["status"] == "pending"]
    expect(pending, f"no pending bank-detail change: {ch}")
    c["s5_change"] = pending[0]["id"]
    r = c.api_post("finance", f"/vendors/{c['s4_vendor']}/verify-payment-change",
               json={"change_request_id": c["s5_change"], "channel": "phone_on_file", "approve": True})
    expect(r.status_code == 403, f"the submitter verified their own change: {r.status_code}")
    return f"submitted by {pending[0]['submitted_by']} → verifying it themselves refused (403)"


def s5_verify(c):
    r = c.api_post("admin", f"/vendors/{c['s4_vendor']}/verify-payment-change",
               json={"change_request_id": c["s5_change"], "channel": "phone_on_file", "approve": True,
                     "notes": "Called the number on file; details confirmed"})
    expect(r.status_code == 200, f"{r.status_code} {r.text[:200]}")
    ch = next(x for x in c.api_get("admin", f"/vendors/{c['s4_vendor']}/payment-changes").json()["data"]
              if x["id"] == c["s5_change"])
    expect(ch["status"] == "verified" and ch["verified_by"] == "admin@demo.example.com"
           and ch["verification_channel"] == "phone_on_file", ch)
    return "verified by admin@demo.example.com by phone · vendor's bank details active"


s5.steps = [
    Step("As <b>finance</b> (who entered the bank details): vendor page → Payment Detail Changes → Verify.",
         "Document & Vendor", "—",
         "<b>Refused</b>: the person who submitted a change can't verify it. Invoices for this vendor are held until it's verified.",
         s5_self, ("finance", lambda c: f"/app/vendors/{c['s4_vendor']}", "text=Payment Detail Changes")),
    Step("As <b>admin</b>: same page → Verify, channel “phone number on file”, with a note.",
         "Document & Vendor", "— (audit log entry)",
         "Change <b>Verified</b> with who, how and when; held payments for the vendor are released.",
         s5_verify, ("admin", lambda c: f"/app/vendors/{c['s4_vendor']}", "text=Payment Detail Changes")),
]


# ── run ────────────────────────────────────────────────────────────────────

class Browser:
    def __init__(self, enabled):
        self.enabled, self.pages, self.pw, self.browser = enabled, {}, None, None

    async def start(self):
        if not self.enabled:
            return
        from playwright.async_api import async_playwright
        self.pw = await async_playwright().start()
        self.browser = await self.pw.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH") or None)

    async def stop(self):
        if self.browser:
            await self.browser.close()
            await self.pw.stop()

    async def shot(self, role, path, anchor, out):
        if not self.enabled:
            return None
        if role not in self.pages:
            ctx = await self.browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme="light")
            p = await ctx.new_page()
            await p.goto(BASE + "/login")
            await p.fill("#email", f"{role}@demo.example.com")
            await p.fill("#password", PASSWORD)
            await p.click("button[type=submit]")
            await p.wait_for_url("**/app**")
            self.pages[role] = p
        p = self.pages[role]
        await p.goto(BASE + path)
        await p.wait_for_timeout(2500)
        if anchor:
            try:
                await p.locator(anchor).first.evaluate("e => e.scrollIntoView({block: 'start'})")
                await p.evaluate("window.scrollBy(0, -80)")
                await p.wait_for_timeout(300)
            except Exception:
                pass
        os.makedirs(os.path.dirname(out), exist_ok=True)
        await p.screenshot(path=out, clip={"x": 224, "y": 0, "width": 1216, "height": 900})
        return os.path.relpath(out, os.path.dirname(HTML_OUT))


async def run(selected, screens):
    c = Ctx(run=uuid.uuid4().hex[:6].upper())
    c["rng"] = random.Random(c["run"])
    c["run_digits"] = str(int(c["run"], 16))[:7].rjust(7, "0")
    b = Browser(screens)
    await b.start()
    print(f"Demo run {c['run']} against {BASE}")
    try:
        for sc in S:
            if sc.num not in selected:
                continue
            print(f"\n{sc.num}. {sc.title}")
            broken = False
            for i, st in enumerate(sc.steps, 1):
                if broken:
                    st.result, st.note = "skipped", "an earlier step failed"
                    print(f"   - {i}. skipped")
                    continue
                try:
                    st.note = st.run(c) or ""
                    st.result = "ok"
                except Exception as e:     # StepFailed, KeyError on a changed API, timeouts…
                    st.result, st.note = "failed", f"{type(e).__name__}: {e}"
                    broken = True
                print(f"   {'✓' if st.result == 'ok' else '✗'} {i}. {st.note}")
                if st.shot and st.result == "ok":
                    role, path_fn, *anchor = st.shot
                    try:
                        st.image = await b.shot(role, path_fn(c), anchor[0] if anchor else None,
                                                os.path.join(SHOTS, f"{sc.num}-{i:02d}.png"))
                    except Exception as e:
                        st.note += f" (screenshot failed: {str(e).splitlines()[0]})"
    finally:
        await b.stop()
    return c


def write_html(ran, run_id):
    steps = [st for sc in S if sc.num in ran for st in sc.steps]
    ok = sum(st.result == "ok" for st in steps)
    stamp = datetime.now().strftime("%d %b %Y, %H:%M")
    def badge(st):
        return {"ok": '<span class="pill g">as described</span>', "failed": '<span class="pill r">failed</span>',
                "skipped": '<span class="pill n">skipped</span>', "not run": '<span class="pill n">not run</span>'}[st.result]

    blocks = []
    for sc in S:
        rows = []
        for i, st in enumerate(sc.steps, 1):
            img = (f'<a href="{st.image}" target="_blank" rel="noopener"><img src="{st.image}" alt="Step {i}" loading="lazy"></a>'
                   if st.image else (f'<a href="demo/{sc.num}-{i:02d}.png" target="_blank" rel="noopener"><img src="demo/{sc.num}-{i:02d}.png" alt="Step {i}" loading="lazy"></a>'
                                     if os.path.exists(os.path.join(SHOTS, f"{sc.num}-{i:02d}.png")) else '<span class="muted">—</span>'))
            rows.append(f"""<tr><td class="n">{i}</td><td>{st.do}</td><td><b>{html.escape(st.agent)}</b><br><code>{html.escape(st.event)}</code></td>
<td>{st.see}<div class="res">{badge(st)} <span class="muted">{html.escape(st.note)}</span></div></td><td class="pic">{img}</td></tr>""")
        blocks.append(f"""<section class="sc" id="s{sc.num}"><h2><span>{sc.num}</span>{html.escape(sc.title)}</h2>
<p class="meta"><b>Proves:</b> {html.escape(sc.proves)} · <b>Roles:</b> {html.escape(sc.roles)} · ~{sc.minutes} min</p>
<div class="tblwrap"><table><thead><tr><th>#</th><th>Do</th><th>Agent · event</th><th>You should see</th><th>Screen</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div></section>""")

    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Demo Script</title>
<style>
  :root {{ --bg:#f4f6f9; --panel:#fff; --ink:#172033; --muted:#5d6879; --line:#d6dce5; --accent:#2563c9; --ok:#1d8a4a; --bad:#c2412d; --plan:#8b95a3; }}
  :root[data-theme="dark"] {{ --bg:#0e1218; --panel:#161c24; --ink:#e6ebf1; --muted:#9aa5b4; --line:#2a333f; --accent:#7aa7f2; --ok:#4cc27f; --bad:#f07a62; --plan:#7d8796; }}
  @media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --bg:#0e1218; --panel:#161c24; --ink:#e6ebf1; --muted:#9aa5b4; --line:#2a333f; --accent:#7aa7f2; --ok:#4cc27f; --bad:#f07a62; --plan:#7d8796; }} }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink); font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }}
  .page {{ max-width:1240px; margin:0 auto; padding:22px 16px 48px; }}
  h1 {{ margin:0 0 4px; font-size:22px; }} a {{ color:var(--accent); }}
  .muted {{ color:var(--muted); font-size:12.5px; }}
  .card {{ background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:12px 14px; margin:12px 0; }}
  pre {{ margin:6px 0; background:color-mix(in srgb,var(--line) 30%,var(--panel)); border:1px solid var(--line); border-radius:8px; padding:9px 11px; overflow-x:auto; font:12.5px/1.5 ui-monospace,Menlo,monospace; }}
  code {{ font:12px ui-monospace,Menlo,monospace; }}
  .toc {{ display:flex; flex-wrap:wrap; gap:8px; margin:10px 0; }}
  .toc a {{ background:var(--panel); border:1px solid var(--line); border-radius:999px; padding:4px 12px; text-decoration:none; color:var(--ink); font-size:13px; }}
  .sc {{ margin-top:22px; }}
  .sc h2 {{ font-size:17px; display:flex; align-items:center; gap:10px; margin:0 0 4px; }}
  .sc h2 span {{ background:var(--accent); color:#fff; border-radius:999px; width:26px; height:26px; display:inline-flex; align-items:center; justify-content:center; font-size:13px; }}
  .meta {{ margin:0 0 8px; color:var(--muted); font-size:13px; }}
  .tblwrap {{ overflow-x:auto; border:1px solid var(--line); border-radius:10px; background:var(--panel); }}
  table {{ border-collapse:collapse; width:100%; min-width:900px; font-size:13px; }}
  th, td {{ text-align:left; vertical-align:top; padding:9px 10px; border-bottom:1px solid var(--line); }}
  th {{ color:var(--muted); font-weight:600; font-size:12px; }}
  td.n {{ width:28px; color:var(--accent); font-weight:700; }}
  td:nth-child(2) {{ width:28%; }} td:nth-child(3) {{ width:17%; }}
  td.pic {{ width:230px; }} td.pic img {{ width:220px; aspect-ratio:4/3; object-fit:cover; object-position:top left; border:1px solid var(--line); border-radius:6px; display:block; }}
  .res {{ margin-top:6px; }}
  .pill {{ display:inline-block; font-size:11px; font-weight:700; border:1px solid; border-radius:999px; padding:0 7px; }}
  .pill.g {{ color:var(--ok); }} .pill.r {{ color:var(--bad); }} .pill.n {{ color:var(--plan); }}
  .sum {{ font-weight:700; color:{'var(--ok)' if ok == len(steps) else 'var(--bad)'}; }}
</style></head>
<body><div class="page">
  <h1>Demo script</h1>
  <p class="muted">Five scenarios, each step: what to do, which agent acts and what event it sends, and what you should see. Generated by <code>tests/e2e/demo_scenarios.py</code>, which performs every step on the running stack first — the result and screenshot in each row are from that run.</p>
  <div class="card"><b>Last verified:</b> {stamp} (run <code>{run_id}</code>) · <span class="sum">{ok} / {len(steps)} steps as described</span>
    · see also <a href="showcase.html">showcase.html</a> (what to say) and <a href="project-flow.html">project-flow.html</a> (status)</div>
  <div class="card"><b>Before you start</b> — from a fresh clone:
<pre>./run.sh                              # first run builds everything
./scripts/seed-demo-data.sh           # demo accounts (password DemoPass123!), demo vendor, licences, stock
./scripts/download-models.sh          # optional: LayoutLMv3 + Legal-BERT
python tests/e2e/demo_scenarios.py    # optional: run all five once and refresh this page (~4 min)</pre>
  Log in at <a href="http://localhost:8080">localhost:8080</a> as <code>requester@</code>, <code>approver@</code>, <code>finance@</code> or <code>admin@demo.example.com</code>. Use a private window per role. Scenario 3 continues scenario 2's order; scenario 5 continues scenario 4's vendor. If a row here is red, that step is broken on this machine — fix or skip it before presenting.</div>
  <nav class="toc">{''.join(f'<a href="#s{sc.num}">{sc.num}. {html.escape(sc.title)}</a>' for sc in S)}</nav>
  {''.join(blocks)}
</div>
<script>
try {{ const t = localStorage.getItem("theme"); if (t) document.documentElement.setAttribute("data-theme", t); }} catch (e) {{}}
</script>
</body></html>
"""
    with open(HTML_OUT, "w") as f:
        f.write(page)
    return ok, len(steps)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    selected = {int(a) for a in args} or {sc.num for sc in S}
    if (3 in selected and 2 not in selected) or (5 in selected and 4 not in selected):
        sys.exit("Scenario 3 needs 2, and 5 needs 4 (they continue them).")
    c = asyncio.run(run(selected, "--no-screens" not in sys.argv))
    ok, total = write_html(selected, c["run"])
    print(f"\n{'=' * 60}\n  demo script: {ok} / {total} steps as described → {os.path.relpath(HTML_OUT, ROOT)}\n{'=' * 60}")
    sys.exit(0 if ok == total else 1)


if __name__ == "__main__":
    main()
