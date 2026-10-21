"""Screenshots of each module's process for docs/index.html#showcase, taken from
the running stack — so if a pipeline breaks, the pictures show it (and the
script says which step failed). Saved to docs/showcase/<module>/NN-*.png.

    pip install -r tests/e2e/requirements.txt playwright
    ./scripts/seed-demo-data.sh            # demo accounts and data
    python tests/e2e/showcase_screens.py   # all modules (~3 min)
    python tests/e2e/showcase_screens.py sanctions fallback   # some

It changes real state, like a presenter would: uploads two documents, runs
a sanctions screening, and turns the model-fallback rule on and back off.
CHROMIUM_PATH points at an existing Chromium instead of Playwright's own.
"""
import asyncio
import os
import sys
import time

import requests
from playwright.async_api import async_playwright

BASE = os.environ.get("GATEWAY", "http://localhost:8080")
API = BASE + "/api"
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "docs", "showcase")
DOCS = os.path.join(ROOT, "data", "synthetic-invoices")
PASSWORD = "DemoPass123!"
VENDOR = "11111111-1111-1111-1111-111111111111"     # demo vendor (seed-demo-data.sh)
DEMO_REQUEST = "22222222-2222-2222-2222-222222222222"  # approved request (seed-demo-data.sh)
LICENCE_DROPOFF = "33333333-0000-0000-0000-000000000003"   # Docker Pro
failures: list[str] = []


def token(role: str) -> str:
    r = requests.post(f"{API}/auth/login", json={"email": f"{role}@demo.example.com", "password": PASSWORD}, timeout=30)
    r.raise_for_status()
    d = r.json()
    return d.get("access_token") or d["data"]["access_token"]


def H(tok):
    return {"Authorization": f"Bearer {tok}"}


def set_rule(tok, key, value, why):
    r = requests.patch(f"{API}/admin/business-rules/{key}", headers=H(tok), timeout=30,
                       json={"new_value": value, "justification": why})
    r.raise_for_status()


def upload(tok, name) -> str:
    with open(os.path.join(DOCS, name), "rb") as f:
        r = requests.post(f"{API}/documents/upload", headers=H(tok), timeout=60,
                          files={"file": (name, f.read(), "application/pdf" if name.endswith(".pdf") else "image/png")})
    r.raise_for_status()
    return r.json()["data"]["document_id"]


def wait_document(tok, doc_id, timeout=180) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        d = requests.get(f"{API}/documents/{doc_id}", headers=H(tok), timeout=30).json().get("data", {})
        if d.get("status") in ("classified", "failed", "rejected"):
            return d
        time.sleep(3)
    raise TimeoutError(f"document {doc_id} still processing after {timeout}s")


class Shots:
    def __init__(self, browser):
        self.browser, self.pages = browser, {}

    async def page(self, role):
        if role not in self.pages:
            ctx = await self.browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme="light")
            p = await ctx.new_page()
            await p.goto(BASE + "/login")
            await p.fill("#email", f"{role}@demo.example.com")
            await p.fill("#password", PASSWORD)
            await p.click("button[type=submit]")
            await p.wait_for_url("**/app**")
            self.pages[role] = p
        return self.pages[role]

    async def shot(self, module, name, role, path=None, wait=None, scroll_to=None, page=None):
        """Opens `path` (unless None — then shoots the page as it is), waits
        for `wait`, scrolls `scroll_to` to the top, saves the viewport."""
        p = page or await self.page(role)
        try:
            if path:
                await p.goto(BASE + path)
            if wait:
                await p.locator(wait).first.wait_for(timeout=20000)
            await p.wait_for_timeout(1200)
            if scroll_to:
                await p.locator(scroll_to).first.evaluate("e => e.scrollIntoView({block: 'start'})")
                await p.evaluate("window.scrollBy(0, -80)")
                await p.wait_for_timeout(400)
        except Exception as e:
            failures.append(f"{module}/{name}: {wait or scroll_to} not found ({str(e).splitlines()[0]})")
        os.makedirs(os.path.join(OUT, module), exist_ok=True)
        # The page without the left navigation, so thumbnails stay readable.
        await p.screenshot(path=os.path.join(OUT, module, name), clip={"x": 224, "y": 0, "width": 1216, "height": 900})
        print("saved", f"docs/showcase/{module}/{name}")
        return p


# ── modules ─────────────────────────────────────────────────────────────────

async def intake(s, admin):
    """A document arrives, is classified and read (FR-29 classifier, FR-11 extraction)."""
    p = await s.shot("intake", "01-documents.png", "finance", "/app/documents", "text=Upload documents")
    await p.get_by_role("button", name="Upload documents").click()
    await p.locator("input[type=file]").set_input_files(os.path.join(DOCS, "06_invoice_hpindiasalespvtltd_INV-2026-00007.pdf"))
    await s.shot("intake", "02-file-chosen.png", "finance", wait="text=06_invoice")
    await p.get_by_role("button", name="Upload 1 file").click()
    await s.shot("intake", "03-processing.png", "finance", wait="text=Close — processing continues")
    try:
        await p.get_by_role("button", name="Done").wait_for(timeout=180000)
    except Exception:
        failures.append("intake: pipeline didn't finish within 3 min")
    await s.shot("intake", "04-processed.png", "finance")
    docs = requests.get(f"{API}/documents/?limit=5", headers=H(admin), timeout=30).json()["data"]
    doc = next((d for d in docs if "INV-2026-00007" in (d.get("original_filename") or "")), docs[0])
    await s.shot("intake", "05-document-detail.png", "finance", f"/app/documents/{doc['id']}", "text=Extracted Fields")
    await s.shot("intake", "06-extracted-fields.png", "finance", scroll_to="text=Extracted Fields")


async def fallback(s, admin):
    """FR-08: force the primary model off, upload, see the fallback in the routing log."""
    set_rule(admin, "dev.force_model_fallback", ["extraction"], "Showcase: demonstrate the model fallback")
    try:
        p = await s.shot("fallback", "01-rule-on.png", "admin", "/app/business-rules", "text=Risk & Compliance")
        await p.get_by_role("tab", name="Risk & Compliance").or_(p.get_by_text("Risk & Compliance", exact=True)).first.click()
        await p.get_by_placeholder("Search rules in this section...").fill("fallback")
        await s.shot("fallback", "01-rule-on.png", "admin", wait="text=Force Model Fallback")
        doc_id = upload(admin, "09_invoice_zohocorporation_INV-2026-00010.png")
        wait_document(admin, doc_id)
        await s.shot("fallback", "02-routing-log.png", "admin", "/app/system-health", "text=Model Routing Log",
                     scroll_to="text=Model Routing Log")
    finally:
        set_rule(admin, "dev.force_model_fallback", [], "Showcase finished: fallback off again")


async def clauses(s, admin):
    """FR-13: Legal-BERT reads the contract's clauses; the routing log shows it."""
    contracts = requests.get(f"{API}/contracts/?limit=5", headers=H(admin), timeout=30).json()["data"]
    if not contracts:
        failures.append("clauses: no contracts — run tests/e2e/invoice_lifecycle.py first")
        return
    cid = contracts[0]["id"]
    await s.shot("clauses", "01-contract.png", "finance", f"/app/contracts/{cid}", "text=Contract text")
    await s.shot("clauses", "02-contract-text.png", "finance", scroll_to="text=Contract text")
    await s.shot("clauses", "03-routing-log.png", "admin", "/app/system-health", "text=legal_bert_primary",
                 scroll_to="text=Model Routing Log")


async def sanctions(s, admin):
    """FR-14: screen a vendor against the consolidated sanctions list."""
    vendors = requests.get(f"{API}/vendors/?limit=200", headers=H(admin), timeout=30).json()["data"]
    listed = next((v for v in vendors if "rosoboronexport" in v["name"].lower()), None)
    if listed is None:
        # A fresh stack has no vendor on the list: onboard one named like a
        # listed exporter, the way finance would.
        r = requests.post(f"{API}/vendors/onboard", headers=H(token("finance")), timeout=60, json={
            "name": "Rosoboronexport OJSC", "contact_email": "info@rosoboronexport.example", "category": "Hardware",
            "confirm": ["no_gstin"], "no_gstin_reason": "Foreign vendor (Russia), not registered for GST in India"})
        if r.status_code != 201:
            failures.append(f"sanctions: onboarding the listed vendor failed: {r.status_code} {r.text[:200]}")
        else:
            d = r.json()["data"]
            listed = d if "id" in d else d["vendor"]
    for i, (vid, label) in enumerate([(VENDOR, "clean"), (listed and listed["id"], "match")]):
        if not vid:
            failures.append("sanctions: test vendor 'Rosoboronexport OJSC' not found")
            continue
        p = await s.shot("sanctions", f"0{2 * i + 1}-{label}-before.png", "finance", f"/app/vendors/{vid}",
                         "text=Sanctions Screening", scroll_to="text=Sanctions Screening")
        await p.get_by_role("button", name="Screen now").click()
        await p.wait_for_timeout(2500)
        await s.shot("sanctions", f"0{2 * i + 2}-{label}-screened.png", "finance", scroll_to="text=Sanctions Screening")


async def licences(s, admin):
    """FR-32: licence usage, the anomaly score and the reasons behind it."""
    await s.shot("licences", "01-licences.png", "admin", "/app/licenses", "text=Docker Pro")
    await s.shot("licences", "02-usage-trend.png", "admin", f"/app/licenses/{LICENCE_DROPOFF}",
                 "text=Usage Trend Analysis", scroll_to="text=Usage Trend Analysis")
    await s.shot("licences", "03-reasons.png", "admin", scroll_to="text=Why was this flagged?")


async def rules(s, admin):
    """FR-09: business rules, edited live with history."""
    await s.shot("rules", "01-business-rules.png", "admin", "/app/business-rules", "text=Business Rules")


async def reliability(s, admin):
    """FR-06 / FR-31: every event kept, failed events parked, notifications."""
    await s.shot("reliability", "01-kafka-log.png", "admin", "/app/control-panel?section=processing", "text=Kafka log",
                 scroll_to="text=Kafka log")
    await s.shot("reliability", "02-failed-events.png", "admin", scroll_to="text=Failed events")
    await s.shot("reliability", "03-notifications.png", "admin", "/app/notifications", "main")


async def onboarding(s, admin):
    """Vendor onboarding: GSTIN check digit, look-alike warning (fraud guard)."""
    p = await s.shot("onboarding", "01-vendors.png", "finance", "/app/vendors", "text=Onboard vendor")
    await p.get_by_role("button", name="Onboard vendor").click()
    await p.get_by_placeholder("Acme Cloud Pvt Ltd").fill("Acme IT Suplies Inc")
    await p.get_by_placeholder("27AAPFU0939F1ZV").fill("27AAPFU0939F1ZX")
    await p.get_by_role("button", name="Check profile").click()
    await p.wait_for_timeout(3000)
    await s.shot("onboarding", "02-checks.png", "finance")
    await p.keyboard.press("Escape")


async def approval(s, admin):
    """Request → approval queue → lifecycle."""
    await s.shot("approval", "01-approval-queue.png", "approver", "/app/approvals", "main")
    reqs = requests.get(f"{API}/requests/?limit=20", headers=H(admin), timeout=30).json()["data"]
    req = next((r for r in reqs if r.get("status") in ("ordered", "fulfilled", "invoice_received", "contract_signed")), reqs[0])
    await s.shot("approval", "02-request-lifecycle.png", "admin", f"/app/requests/{req['id']}", "main")


async def contract(s, admin):
    """Contract with the vendor's risk shown before signing."""
    contracts = requests.get(f"{API}/contracts/?limit=20", headers=H(admin), timeout=30).json()["data"]
    unsigned = next((c for c in contracts if c.get("status") in ("draft", "pending_signature")), None)
    if unsigned is None:
        # Everything is signed (e.g. right after demo_scenarios.py): generate
        # one from the seeded approved request, as seed-demo-data.sh suggests.
        r = requests.post(f"{API}/contracts/generate", headers=H(token("finance")), timeout=60,
                          json={"purchase_request_id": DEMO_REQUEST, "template_name": "hardware_purchase"})
        r.raise_for_status()
        unsigned = r.json()["data"]
    await s.shot("contract", "01-contract-risk.png", "finance", f"/app/contracts/{unsigned['id']}", "text=Vendor risk")
    await s.shot("contract", "02-renewal-timeline.png", "finance", scroll_to="text=Renewal Timeline")
    # Deterministic risk scorecard (merged from updated_risk): every check, its points and source.
    await s.shot("contract", "03-vendor-risk.png", "finance", f"/app/vendors/{VENDOR}/risk", "text=Recompute Rating")


async def inventory(s, admin):
    await s.shot("inventory", "01-reorder.png", "admin", "/app/inventory", "text=Reorder Suggestions",
                 scroll_to="text=Reorder Suggestions")


def _partly_received(admin) -> str:
    """A request with 30 of 50 laptops received (made if there is none)."""
    import hashlib, hmac, json
    from datetime import datetime, timezone
    reqs = requests.get(f"{API}/requests/?limit=200", headers=H(admin), timeout=30).json()["data"]
    found = next((r for r in reqs if r.get("status") == "partially_received"), None)
    if found:
        return found["id"]
    req_t, appr, fin = token("requester"), token("approver"), token("finance")
    pr = requests.post(f"{API}/requests/", headers=H(req_t), timeout=30, json={
        "request_type": "hardware", "requested_by": "x", "department": "Engineering", "amount": 4250000, "currency": "INR",
        "vendor_id": VENDOR, "items": [{"name": "Dell Latitude 5540, 16 GB", "quantity": 50, "unit_price": 85000}]}).json()["data"]
    for tok in (appr, fin, admin):
        if requests.get(f"{API}/requests/{pr['id']}", headers=H(admin), timeout=30).json()["data"]["status"] != "pending_approval":
            break
        requests.post(f"{API}/requests/{pr['id']}/approve", headers=H(tok), json={"comments": "showcase"}, timeout=30)
        time.sleep(3)
    contract = None
    for _ in range(30):
        contract = next((c for c in requests.get(f"{API}/contracts/?limit=100", headers=H(admin), timeout=30).json()["data"]
                         if c["purchase_request_id"] == pr["id"] and c["status"] == "pending_signature"), None)
        if contract:
            break
        time.sleep(2)
    if contract is None:
        raise RuntimeError("no contract went out for the showcase request")
    secret = os.environ.get("ESIGN_WEBHOOK_SECRET", "dev-esign-secret-change-me")
    body = {"provider_event_id": f"evt-showcase-{pr['id'][:8]}", "contract_id": contract["id"], "signed_by": "vendor@acme.example",
            "signed_at": datetime.now(timezone.utc).isoformat()}
    body["signature"] = hmac.new(secret.encode(), json.dumps(body, sort_keys=True, separators=(",", ":")).encode(), hashlib.sha256).hexdigest()
    requests.post(f"{API}/webhooks/esign", json=body, timeout=30)
    time.sleep(4)
    r = requests.post(f"{API}/requests/{pr['id']}/receipts", headers=H(req_t), timeout=30, json={
        "lines": [{"line_no": 0, "quantity": 30, "asset_tags": ["LT-0101", "LT-0102", "LT-0103"]}], "notes": "first delivery"})
    r.raise_for_status()
    return pr["id"]


SHOWCASE_RFQ = "Developer laptop refresh, Q3"
# Real-looking demo vendors only, never the e2e suites' test vendors.
SHOWCASE_VENDORS = ["Acme IT Supplies Inc", "Dell Technologies India Pvt Ltd", "HP India Sales Pvt Ltd", "Freshworks Inc",
                    "Lenovo India Pvt Ltd"]


def _showcase_rfq() -> str:
    """A closed RFQ between demo vendors, ready to award (made once)."""
    from datetime import datetime, timedelta, timezone
    fin = token("finance")
    existing = next((r for r in requests.get(f"{API}/rfqs/", headers=H(fin), timeout=30).json()["data"]
                     if r["title"] == SHOWCASE_RFQ and r["status"] in ("closed", "awarded")), None)
    if existing:
        return existing["id"]
    names = {v["name"]: v["id"] for v in requests.get(f"{API}/vendors/?limit=500", headers=H(fin), timeout=30).json()["data"]}
    vendors = [names[n] for n in SHOWCASE_VENDORS if n in names][:3]
    if len(vendors) < 2:
        raise RuntimeError(f"need two of {SHOWCASE_VENDORS} for the RFQ shot (run ./scripts/reset-demo.sh)")
    r = requests.post(f"{API}/rfqs/", headers=H(fin), timeout=30, json={
        "title": SHOWCASE_RFQ, "department": "Engineering", "request_type": "hardware", "sealed": True,
        "items": [{"name": "Developer laptop, 32 GB, 3-year on-site warranty", "quantity": 25}],
        "vendor_ids": vendors, "deadline": (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()})
    r.raise_for_status()
    rid = r.json()["data"]["id"]
    terms = [(2287500, 7, 36, 4), (2190000, 21, 12, 3), (2340000, 5, 36, 5)]
    for vid, (total, lead, warranty, support) in zip(vendors, terms):
        requests.post(f"{API}/rfqs/{rid}/responses", headers=H(fin), timeout=30, json={
            "vendor_id": vid, "total_inr": total, "lead_time_days": lead, "warranty_months": warranty,
            "support_rating": support}).raise_for_status()
    requests.post(f"{API}/rfqs/{rid}/close", headers=H(fin), timeout=30).raise_for_status()
    return rid


async def expansion(s, admin):
    """Feature expansion Phases 1-3: budgets, obligations, catalog, RFQ,
    partial receipts, vendor scorecard."""
    await s.shot("expansion", "01-budgets.png", "finance", "/app/budgets", "text=Budgeted")
    contracts = requests.get(f"{API}/contracts/?limit=200", headers=H(admin), timeout=30).json()["data"]
    with_obligations = next((c for c in contracts if c.get("status") == "signed" and c.get("template_used") == "saas_subscription"
                             and requests.get(f"{API}/contracts/{c['id']}/obligations", headers=H(admin), timeout=30)
                             .json()["data"]["obligations"]), None)
    if with_obligations is None:
        raise RuntimeError("no signed SaaS contract with obligations (run tests/e2e/obligation_flow.py first)")
    await s.shot("expansion", "02-obligations.png", "finance", f"/app/contracts/{with_obligations['id']}",
                 "text=SLA uptime and service credits", scroll_to="h3:text-is('Obligations')")
    await s.shot("expansion", "03-catalog.png", "requester", "/app/catalog", "text=Dell Latitude 5540")
    rfq_id = _showcase_rfq()
    await s.shot("expansion", "04-rfq-comparison.png", "finance", f"/app/sourcing/{rfq_id}", "text=Comparison")
    rid = _partly_received(admin)
    await s.shot("expansion", "05-partial-receipt.png", "requester", f"/app/requests/{rid}", "text=Record delivery",
                 scroll_to="text=Partly received: the rest")
    await s.shot("expansion", "06-scorecard.png", "finance", f"/app/vendors/{VENDOR}", "text=On-time deliveries",
                 scroll_to="h2:text-is('Scorecard')")


async def gst(s, admin):
    """Feature expansion Phase 4: the GST check of an invoice, the GST and TDS
    page, GSTR-2B reconciliation, MSME deadlines and the vendor tax profile.
    Uses the invoices tests/e2e/gst_flow.py leaves behind (run it first)."""
    invoices = requests.get(f"{API}/gst/invoices", headers=H(admin), timeout=30).json()["data"]
    flagged = next((i for i in invoices if any("expected CGST + SGST" in x for x in i["issues"])), None)
    verified = next((i for i in invoices if i["status"] == "ok" and i["einvoice_verified"]), None)
    if not flagged or not verified:
        raise RuntimeError("no GST test invoices this month (run tests/e2e/gst_flow.py first)")
    await s.shot("gst", "01-tax-check-flagged.png", "finance", f"/app/documents/{flagged['document_id']}",
                 "h2:text-is('GST check')", scroll_to="h2:text-is('GST check')")
    await s.shot("gst", "02-tax-check-einvoice.png", "finance", f"/app/documents/{verified['document_id']}",
                 "h2:text-is('GST check')", scroll_to="h2:text-is('GST check')")
    p = await s.shot("gst", "03-gst-page.png", "finance", "/app/gst", "text=Invoices this month")
    await p.locator("text=Earlier uploads").locator("button").first.click()
    await s.shot("gst", "04-gstr2b.png", "finance", wait="text=Input tax credit at risk",
                 scroll_to="h2:text-is('GSTR-2B reconciliation')")
    await p.get_by_role("tab", name="TDS and MSME").click()
    await s.shot("gst", "05-tds-msme.png", "finance", wait="h2:text-is('MSME payment deadlines')")
    if verified.get("vendor_id"):
        await s.shot("gst", "06-vendor-tax-profile.png", "finance", f"/app/vendors/{verified['vendor_id']}",
                     "text=Tax profile", scroll_to="text=Tax profile")


async def cpanel(s, admin):
    """The Control Panel (final checklist A1-A7): folders and dropped files,
    approvals, notification templates, contracts and e-signatures, and a
    document's extracted fields with each stage's validation result."""
    cp = "/app/control-panel"
    await s.shot("cpanel", "01-overview.png", "admin", cp, "text=In input folder")
    await s.shot("cpanel", "02-documents.png", "admin", f"{cp}?section=documents", "text=Dropped files")
    await s.shot("cpanel", "03-approvals.png", "admin", f"{cp}?section=approvals", "text=Awaiting approval")
    await s.shot("cpanel", "04-templates.png", "admin", f"{cp}?section=notifications", "text=Message body")
    await s.shot("cpanel", "05-esignatures.png", "admin", f"{cp}?section=esign", "text=Contract documents",
                 scroll_to="text=Contract documents")
    docs = requests.get(f"{API}/documents/?limit=100", headers=H(admin), timeout=30).json()["data"]
    doc = next((d for d in docs if d["status"] == "classified" and d.get("document_type") == "invoice"), None)
    if doc:
        await s.shot("cpanel", "06-extraction.png", "admin", f"/app/documents/{doc['id']}", "text=Every extracted field",
                     scroll_to="text=Every extracted field")
    else:
        failures.append("cpanel/06-extraction.png: no classified invoice to show")


MODULES = {f.__name__: f for f in (intake, fallback, clauses, sanctions, licences, rules, reliability, onboarding,
                                    approval, contract, inventory, expansion, gst, cpanel)}


async def main(names):
    admin = token("admin")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH") or None)
        s = Shots(browser)
        for name in names:
            try:
                await MODULES[name](s, admin)
            except Exception as e:
                failures.append(f"{name}: {type(e).__name__}: {str(e).splitlines()[0]}")
        await browser.close()
    if failures:
        print("\nSTEPS THAT FAILED (the screenshots show what was on screen):")
        for f in failures:
            print("  ✗", f)
        sys.exit(1)
    print("\nall steps OK")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:] or list(MODULES)))
