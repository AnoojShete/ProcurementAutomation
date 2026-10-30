"""Two-party signing through Documenso, done the way people do it on the
platform's pages: the company's signatory signs in Documenso's frame on the
contract page, then the vendor signs through the link emailed to them
(read from Mailpit) on /sign, with no account.

Shared by esign_flow.py, demo_5min.py, demo_scenarios.py, ui_flows.py and
showcase_screens.py. The page-level steps (send_on_page, company_signs,
vendor_signs) take a Playwright page so a recording shows every click;
sign_both() does the whole thing in its own headless browser for the
scripts that otherwise work through the API.
"""
import asyncio
import concurrent.futures
import os
import re
import time

import requests

BASE = os.getenv("GATEWAY", "http://localhost:8080")
API = BASE + "/api"
MAILPIT = os.getenv("MAILPIT", "http://localhost:8025")
PASSWORD = "DemoPass123!"
VENDOR_SIGNER = "Priya Raman"     # a made-up name for the vendor's signatory


def vendor_signer_email(vendor_name, run):
    """A Mailpit-only address for the vendor's signatory, new every run."""
    slug = re.sub(r"[^a-z0-9]+", "", (vendor_name or "vendor").lower())[:20] or "vendor"
    return f"signatory-{run.lower()}@{slug}.example"


def mail_ids(email):
    msgs = requests.get(f"{MAILPIT}/api/v1/search", params={"query": f"to:{email}"}, timeout=30).json().get("messages") or []
    return {m["ID"] for m in msgs}


def vendor_link(email, after_ids=frozenset()):
    """The newest signing link emailed to `email` that isn't in after_ids,
    as (Mailpit message id, link), or (None, None)."""
    msgs = requests.get(f"{MAILPIT}/api/v1/search", params={"query": f"to:{email}"}, timeout=30).json().get("messages") or []
    for m in msgs:
        if m["ID"] in after_ids:
            continue
        text = requests.get(f"{MAILPIT}/api/v1/message/{m['ID']}", timeout=30).json().get("Text", "")
        found = re.search(r"(http\S+/sign#token=[A-Za-z0-9_-]+)", text)
        if found:
            return m["ID"], found.group(1)
    return None, None


def wait_vendor_link(email, after_ids=frozenset(), timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        mid, link = vendor_link(email, after_ids)
        if link:
            return mid, link
        time.sleep(1)
    raise TimeoutError(f"no signing link emailed to {email} within {timeout} s")


def send_via_api(token, contract_id, vendor_email, vendor_name=VENDOR_SIGNER, signer_email="finance@demo.example.com"):
    """What the contract page's Send for signature dialog sends."""
    return requests.post(f"{API}/contracts/{contract_id}/send-for-signature", timeout=60,
                         headers={"Authorization": f"Bearer {token}"}, json={
                             "provider": "documenso", "signer_email": signer_email,
                             "vendor_signer_email": vendor_email, "vendor_signer_name": vendor_name})


async def login(page, role):
    await page.goto(BASE + "/login")
    await page.fill("#email", f"{role}@demo.example.com")
    await page.fill("#password", PASSWORD)
    await page.click("button[type=submit]")
    await page.wait_for_url("**/app**", timeout=20000)


async def _click_in_frame(frame, name, timeout=15000):
    btn = frame.get_by_role("button", name=name, exact=True).last
    await btn.wait_for(timeout=timeout)
    for _ in range(30):
        if await btn.is_enabled():
            break
        await asyncio.sleep(0.3)
    await btn.click()


async def sign_in_frame(page):
    """Signs in Documenso's frame on the page as a person would: go to the
    signature field, draw a signature, then complete and confirm."""
    iframe = page.locator("iframe[src*='/embed/sign/']")
    await iframe.wait_for(timeout=30000)
    # The frame's own "Next Field" bar sits at its bottom edge: scroll the
    # page so all of the frame is on screen (a long header pushes it down).
    await iframe.evaluate("e => e.scrollIntoView({block: 'end'})")
    frame = page.frame_locator("iframe[src*='/embed/sign/']")
    hint = frame.get_by_text("Click to insert field")
    dialog = frame.get_by_role("dialog")
    viewport = page.viewport_size["height"]
    for _ in range(10):
        # "Next Field" scrolls the signature field into view (once the
        # document has rendered); then click the field, just under its hint.
        await _click_in_frame(frame, "Next Field", timeout=30000)
        await page.wait_for_timeout(1200)
        box = await hint.bounding_box() if await hint.count() else None
        if not box or not 0 < box["y"] < viewport - 150:
            continue
        await page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] + 30)
        try:
            await dialog.wait_for(timeout=3000)
            break
        except Exception:
            continue
    await dialog.wait_for(timeout=5000)
    pads = dialog.locator("canvas")
    boxes = [await pads.nth(i).bounding_box() for i in range(await pads.count())]
    box = max((b for b in boxes if b), key=lambda b: b["width"] * b["height"])  # the drawing pad
    # Big enough for Documenso ("Signature is too small" otherwise).
    mid, width = box["y"] + box["height"] / 2, box["width"] - 80
    await page.mouse.move(box["x"] + 40, mid)
    await page.mouse.down()
    for i in range(1, 25):
        await page.mouse.move(box["x"] + 40 + i * width / 24, mid + (55 if i % 2 else -55), steps=4)
    await page.mouse.up()
    await _click_in_frame(dialog, "Sign")          # puts the signature on the field
    await _click_in_frame(frame, "Complete")       # all fields done
    await _click_in_frame(frame.get_by_role("dialog"), "Sign")  # "Are you sure?" -> sign


async def send_on_page(page, vendor_email, vendor_name=VENDOR_SIGNER, pause=0):
    """On a draft contract's page: Send for signature, naming the vendor's
    signatory (the company's signatory defaults to the logged-in user)."""
    await page.get_by_role("button", name="Send for signature").first.click()
    dialog = page.get_by_role("dialog")
    await dialog.locator("#vendor-signer-name").fill(vendor_name)
    await dialog.locator("#vendor-signer-email").fill(vendor_email)
    await page.wait_for_timeout(pause)
    await dialog.get_by_role("button", name="Send", exact=True).click()
    await page.get_by_text("Sent.", exact=False).first.wait_for(timeout=30000)
    await dialog.wait_for(state="hidden", timeout=10000)


async def company_signs(page, acknowledge=True, pause=0):
    """On a contract's page, as the company's signatory: Sign now, tick the
    risk acknowledgement if the vendor isn't cleared, open the frame, sign.
    Returns whether an acknowledgement was asked for."""
    dialog = page.get_by_role("dialog")
    open_frame = dialog.get_by_role("button", name="Open the contract to sign")
    if not await open_frame.count():   # not already open
        await page.get_by_role("button", name="Sign now").first.click()
    await open_frame.wait_for(timeout=20000)
    ack = dialog.get_by_role("checkbox")
    asked = await ack.count() > 0
    if asked and acknowledge:
        await page.wait_for_timeout(pause)
        await ack.first.check()
    await page.wait_for_timeout(pause)
    await open_frame.click()
    await sign_in_frame(page)
    await page.get_by_text("The vendor has been emailed a link to sign").wait_for(timeout=45000)
    return asked


async def vendor_signs(page, link):
    """The vendor's emailed link: /sign on the platform, no account."""
    await page.goto(link)
    await page.get_by_text("Signing for", exact=False).first.wait_for(timeout=20000)
    await sign_in_frame(page)
    await page.get_by_text("Both parties have now signed").wait_for(timeout=45000)


async def _sign_both(contract_id, vendor_email, signer, acknowledge, chromium):
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=chromium or None)
        try:
            ctx = await browser.new_context(viewport={"width": 1400, "height": 1000})
            page = await ctx.new_page()
            await login(page, signer)
            before = mail_ids(vendor_email)
            await page.goto(f"{BASE}/app/contracts/{contract_id}")
            await page.get_by_role("button", name="Sign now").first.wait_for(timeout=30000)
            asked = await company_signs(page, acknowledge)
            await ctx.close()
            _, link = wait_vendor_link(vendor_email, before)
            ctx = await browser.new_context(viewport={"width": 1400, "height": 1000})
            await vendor_signs(await ctx.new_page(), link)
            await ctx.close()
            return asked
        finally:
            await browser.close()


def sign_both(contract_id, vendor_email, signer="finance", acknowledge=True):
    """Both parties sign a contract that is out in Documenso, in a headless
    browser. Runs in its own thread, so it also works from code already
    inside an asyncio loop. Returns whether a risk acknowledgement was asked."""
    coro = _sign_both(contract_id, vendor_email, signer, acknowledge, os.environ.get("CHROMIUM_PATH"))
    with concurrent.futures.ThreadPoolExecutor(1) as pool:
        return pool.submit(asyncio.run, coro).result()
