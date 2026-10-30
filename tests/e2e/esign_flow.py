"""Two-party contract signing through Documenso, on the platform's own pages.

    python tests/e2e/esign_flow.py            # needs the stack + scripts/documenso_setup.py done

A request for Infosys (a scored, real vendor) is approved; its contract is
sent for signature with the vendor's signatory named. Then, in a browser:
finance signs in the Documenso frame on the contract page; the vendor's
emailed link (Mailpit) opens /sign on the platform, no account, where the
vendor signs in the same frame. Checks the access rules on the way (only
the named signer, the right turn, links that stop working), and that the
signed copy is Documenso's PDF with a digital signature.
"""
import asyncio
import os
import sys
import time
import uuid

import requests
from playwright.async_api import async_playwright

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from documenso_signing import mail_ids, sign_in_frame, vendor_link  # noqa: E402

BASE = os.getenv("GATEWAY", "http://localhost:8080")
GW = BASE + "/api"
MAILPIT = os.getenv("MAILPIT", "http://localhost:8025")
PASSWORD = "DemoPass123!"
VENDOR = "Infosys Limited"
HEADLESS = os.getenv("HEADED") != "1"

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(f"  {'✓' if cond else '✗'} {name}" + (f"  [{detail}]" if detail and not cond else ""))
    return bool(cond)


def step(title):
    print(f"\n── {title}")


def login(role):
    r = requests.post(f"{GW}/auth/login", json={"email": f"{role}@demo.example.com", "password": PASSWORD})
    r.raise_for_status()
    return r.json()["data"]["access_token"]


def H(tok):
    return {"Authorization": f"Bearer {tok}"}


def poll(fn, until, timeout=60, interval=1.0):
    deadline = time.time() + timeout
    value = fn()
    while not until(value) and time.time() < deadline:
        time.sleep(interval)
        value = fn()
    return value


def make_contract(req_t, app_t, fin_t, vendor_id, run):
    r = requests.post(f"{GW}/requests/", headers=H(req_t), json={
        "request_type": "saas", "department": "Engineering", "amount": 4800.0, "currency": "INR",
        "vendor_id": vendor_id,
        "items": [{"description": f"E-sign e2e licence {run}", "quantity": 2, "unit_price": 2400.0}],
    })
    r.raise_for_status()
    pr_id = r.json()["data"]["id"]
    chain = r.json()["data"]["approval_chain"]
    for level in chain:
        tok = fin_t if "finance" in level else app_t
        poll(lambda: requests.get(f"{GW}/requests/{pr_id}", headers=H(tok)).json()["data"],
             lambda d: d.get("current_level") in (None, level) or d["status"] != "pending_approval", timeout=15)
        requests.post(f"{GW}/requests/{pr_id}/approve", headers=H(tok), json={"comments": "e-sign e2e"})
    pr = poll(lambda: requests.get(f"{GW}/requests/{pr_id}", headers=H(app_t)).json()["data"],
              lambda d: d["status"] == "approved", timeout=60)
    check("request approved", pr["status"] == "approved", pr["status"])
    contracts = poll(lambda: requests.get(f"{GW}/contracts/?purchase_request_id={pr_id}", headers=H(fin_t)).json()["data"],
                     lambda d: bool(d), timeout=30)
    if not contracts:
        r = requests.post(f"{GW}/contracts/generate", headers=H(fin_t),
                          json={"purchase_request_id": pr_id, "template_name": "saas_subscription"})
        contracts = [r.json()["data"]]
    return contracts[0]["id"]


async def main():
    run = uuid.uuid4().hex[:6]
    vendor_email = f"signatory-{run}@infosys.example"
    req_t, app_t, fin_t = login("requester"), login("approver"), login("finance")
    vendors = requests.get(f"{GW}/vendors/?limit=500", headers=H(fin_t)).json()["data"]
    vendor_id = next(v["id"] for v in vendors if v["name"] == VENDOR)

    step("contract out for signature in Documenso")
    cid = make_contract(req_t, app_t, fin_t, vendor_id, run)
    c = requests.get(f"{GW}/contracts/{cid}", headers=H(fin_t)).json()["data"]
    check("Documenso is the signing provider", c.get("signing_provider") == "documenso", c.get("signing_provider"))
    if c["status"] != "draft":
        sys.exit(f"contract {cid} is {c['status']} (sent automatically?); this run needs a draft")
    r = requests.post(f"{GW}/contracts/{cid}/send-for-signature", headers=H(fin_t),
                      json={"provider": "documenso", "signer_email": "finance@demo.example.com"})
    check("no vendor signatory and none on file -> 400", r.status_code == 400 and "vendor" in r.text, r.text[:150])
    r = requests.post(f"{GW}/contracts/{cid}/send-for-signature", headers=H(fin_t), json={
        "provider": "documenso", "signer_email": "finance@demo.example.com",
        "vendor_signer_email": vendor_email, "vendor_signer_name": "Priya Raman"})
    check("send -> pending_signature", r.status_code == 200 and r.json()["data"]["status"] == "pending_signature", r.text[:200])
    c = requests.get(f"{GW}/contracts/{cid}", headers=H(fin_t)).json()["data"]
    check("out in Documenso", (c.get("esign_provider_ref") or "").startswith("documenso-env-"), c.get("esign_provider_ref"))
    signers = {s["party"]: s for s in c.get("signers") or []}
    check("company signs first, vendor waits",
          signers.get("company", {}).get("status") == "ready" and signers.get("vendor", {}).get("status") == "waiting", signers)
    check("no signing tokens in the contract response", "token" not in str(c.get("signers")).lower())

    step("who may open the signing frame")
    r = requests.post(f"{GW}/contracts/{cid}/signing-session", headers=H(req_t), json={})
    check("requester -> 403", r.status_code == 403, str(r.status_code))
    r = requests.post(f"{GW}/contracts/{cid}/signing-session", headers=H(app_t), json={})
    check("approver (not the named signer) -> 403 not_the_signer",
          r.status_code == 403 and "not_the_signer" in r.text, f"{r.status_code} {r.text[:120]}")
    r = requests.post(f"{GW}/contracts/{cid}/vendor-link", headers=H(fin_t), json={})
    check("vendor link before the company signed -> 400", r.status_code == 400, str(r.status_code))
    r = requests.post(f"{GW}/contracts/vendor-signing/session", json={"link_token": "x" * 43})
    check("made-up vendor link -> 404", r.status_code == 404, str(r.status_code))
    r = requests.post(f"{GW}/webhooks/documenso", headers={"X-Documenso-Secret": "wrong"},
                      json={"event": "DOCUMENT_COMPLETED", "payload": {"externalId": cid}})
    check("webhook with the wrong secret -> 401", r.status_code == 401, str(r.status_code))

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)

        step("finance signs on the contract page")
        ctx = await browser.new_context(viewport={"width": 1400, "height": 1000})
        page = await ctx.new_page()
        await page.goto(f"{BASE}/login")
        await page.fill("input[type=email]", "finance@demo.example.com")
        await page.fill("input[type=password]", PASSWORD)
        await page.keyboard.press("Enter")
        await page.wait_for_url("**/app**", timeout=20000)
        await page.goto(f"{BASE}/app/contracts/{cid}?action=sign")
        await page.get_by_role("dialog").wait_for(timeout=20000)
        ack = page.get_by_role("checkbox")
        if await ack.count():
            await ack.first.check()
        before = mail_ids(vendor_email)
        await page.get_by_role("button", name="Open the contract to sign").click()
        await page.locator("iframe[src*='/embed/sign/']").wait_for(timeout=20000)
        check("signing frame loads on the platform's page", page.url.startswith(f"{BASE}/app/contracts/{cid}"), page.url)
        await sign_in_frame(page)
        if os.getenv("SHOTS"):
            await page.screenshot(path="/tmp/esign-company.png")
        await page.get_by_text("The vendor has been emailed a link to sign").wait_for(timeout=30000)
        c = requests.get(f"{GW}/contracts/{cid}", headers=H(fin_t)).json()["data"]
        signers = {s["party"]: s for s in c.get("signers") or []}
        check("company signed, vendor's turn",
              signers["company"]["status"] == "signed" and signers["vendor"]["status"] == "ready", signers)
        check("contract still pending (one of two signed)", c["status"] == "pending_signature", c["status"])
        await ctx.close()

        step("the vendor's emailed link")
        mid, link = poll(lambda: vendor_link(vendor_email, before), lambda x: x[0] is not None, timeout=20)
        check("vendor emailed a /sign link with the token after #", bool(link) and "/sign#token=" in (link or ""), link)
        r = requests.post(f"{GW}/contracts/{cid}/vendor-link", headers=H(fin_t), json={})
        check("new link -> 200", r.status_code == 200, r.text[:120])
        old_token = link.split("#token=")[1]
        r = requests.post(f"{GW}/contracts/vendor-signing/session", json={"link_token": old_token})
        check("the earlier link stops working", r.status_code == 404, str(r.status_code))
        _, link = poll(lambda: vendor_link(vendor_email, before | {mid}), lambda x: x[0] is not None, timeout=20)
        check("new link emailed", bool(link))
        r = requests.post(f"{GW}/contracts/{cid}/signing-session", headers=H(fin_t), json={"risk_acknowledged": True})
        check("company can't open the frame again after signing -> 400", r.status_code == 400, str(r.status_code))

        step("vendor signs on /sign, no account")
        ctx = await browser.new_context(viewport={"width": 1400, "height": 1000})
        page = await ctx.new_page()
        await page.goto(link)
        await page.get_by_text("Signing for Infosys Limited").wait_for(timeout=20000)
        check("vendor page shows the company already signed", await page.get_by_text("Signed for").count() > 0)
        check("vendor page is the platform's", page.url.startswith(f"{BASE}/sign") and "token=" not in page.url, page.url)
        await sign_in_frame(page)
        if os.getenv("SHOTS"):
            await page.screenshot(path="/tmp/esign-vendor.png")
        await page.get_by_text("Both parties have now signed").wait_for(timeout=30000)
        await ctx.close()
        await browser.close()

    step("executed contract")
    c = poll(lambda: requests.get(f"{GW}/contracts/{cid}", headers=H(fin_t)).json()["data"],
             lambda d: d["status"] == "signed", timeout=20)
    check("contract signed", c["status"] == "signed", c["status"])
    check("signed by both parties", "finance@demo.example.com" in (c.get("signed_by") or "") and vendor_email in (c.get("signed_by") or ""),
          c.get("signed_by"))
    r = requests.get(f"{GW}/contracts/{cid}/signed-document", headers=H(fin_t))
    check("signed copy downloads", r.status_code == 200 and r.content.startswith(b"%PDF"), str(r.status_code))
    check("signed copy carries a digital signature (PAdES /ByteRange)", b"/ByteRange" in r.content)
    r = requests.post(f"{GW}/contracts/vendor-signing/session", json={"link_token": link.split("#token=")[1]})
    check("vendor link after signing shows 'signed', no token",
          r.status_code == 200 and r.json()["data"]["state"] == "signed" and "token" not in r.json()["data"], r.text[:150])
    pr = poll(lambda: requests.get(f"{GW}/requests/{c['purchase_request_id']}", headers=H(app_t)).json()["data"],
              lambda d: d["status"] != "approved", timeout=20)
    check("request moves on after signing", pr["status"] in ("ordered", "contract_signed", "received"), pr["status"])

    passed = sum(ok for _, ok in results)
    print(f"\n{passed}/{len(results)} checks passed (contract {cid})")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
