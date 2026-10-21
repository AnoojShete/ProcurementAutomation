"""The 5-minute demo (docs/demo-5min.html), rehearsed in a real browser.

Walks the presenter's click path as the right roles, checks every "you
should see", times each step against its budget, and records the run as a
captioned video — the backup recording to play if the live demo fails.

    ./run.sh && ./scripts/seed-demo-data.sh
    python tests/e2e/demo_scenarios.py      # realistic history first (once)
    python tests/e2e/showcase_screens.py    # adds the sanctions-listed vendor
    python tests/e2e/demo_5min.py           # → docs/demo/backup-recording.webm
    python tests/e2e/demo_5min.py --quote demo-quote.pdf   # a fresh quote to drop live
    HEADLESS=1 python tests/e2e/demo_5min.py  # no display (the PDF preview stays empty)

It changes state like the presenter would: drops one quote into ./inbox
and signs the contract that comes out of it.
"""
import asyncio
import os
import shutil
import sys
import time
import uuid

import requests
from playwright.async_api import async_playwright

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from demo_scenarios import ROOT, Ctx, brand, doc_pdf, poll  # noqa: E402

import random  # noqa: E402

BASE = os.getenv("GATEWAY", "http://localhost:8080")
API = BASE + "/api"
INBOX = os.path.join(ROOT, "inbox")
OUT = os.path.join(ROOT, "docs", "demo")
PASSWORD = "DemoPass123!"
results: list[tuple[str, float, float, bool, str]] = []


def token(role):
    r = requests.post(f"{API}/auth/login", json={"email": f"{role}@demo.example.com", "password": PASSWORD}, timeout=30)
    r.raise_for_status()
    d = r.json()
    return d.get("access_token") or d["data"]["access_token"]


def get(role, path):
    return requests.get(f"{API}{path}", headers={"Authorization": f"Bearer {token(role)}"}, timeout=30).json()["data"]


class Demo:
    def __init__(self, page):
        self.page, self.role = page, None

    async def caption(self, text):
        # Shown in the recording only: which minute of the script this is.
        await self.page.evaluate("""t => {
            let el = document.getElementById('__demo_caption');
            if (!el) { el = document.createElement('div'); el.id = '__demo_caption';
              el.style.cssText = 'position:fixed;left:16px;bottom:16px;z-index:99999;max-width:60%;padding:8px 12px;'
                + 'background:rgba(24,33,28,.88);color:#fff;font:14px/1.4 system-ui;border-radius:4px;pointer-events:none';
              document.body.appendChild(el); }
            el.textContent = t; }""", text)

    async def login(self, role):
        if self.role == role:
            return
        await self.page.context.clear_cookies()
        await self.page.goto(BASE + "/login")
        await self.page.evaluate("() => { try { localStorage.clear(); sessionStorage.clear(); } catch (e) {} }")
        await self.page.goto(BASE + "/login")
        await self.page.fill("#email", f"{role}@demo.example.com")
        await self.page.fill("#password", PASSWORD)
        await self.page.click("button[type=submit]")
        await self.page.wait_for_url("**/app**")
        self.role = role

    async def open(self, role, path, wait_text, caption):
        await self.login(role)
        await self.page.goto(BASE + path)
        # Only visible matches: a closed modal can hold the same words.
        await self.page.locator(f"text={wait_text} >> visible=true").first.wait_for(timeout=30000)
        await self.caption(caption)

    async def scroll_to(self, text):
        await self.page.locator(f"text={text} >> visible=true").first.scroll_into_view_if_needed()


async def step(name, budget, fn):
    t0 = time.time()
    try:
        note = await fn() or ""
        ok = True
    except Exception as e:  # keep going: the report says which step broke
        note, ok = f"{type(e).__name__}: {str(e).splitlines()[0][:160]}", False
    took = time.time() - t0
    results.append((name, took, budget, ok, note))
    print(f"  {'✓' if ok else '✗'} {name:<44} {took:5.0f}s / {budget:>3}s  {note}")


async def main():
    c = Ctx(run=uuid.uuid4().hex[:6].upper())
    c["rng"] = random.Random(c["run"])
    listed = next((v for v in get("admin", "/vendors/?limit=200") if "rosoboronexport" in v["name"].lower()), None)
    def acknowledged_high(x):
        cert = get("admin", f"/contracts/{x['id']}/signature-certificate") or {}
        risk = cert.get("vendor_risk_at_signing") or {}
        # High, or Unrated (checks incomplete) under the deterministic scorecard
        return risk.get("risk_band") in ("High", "Unrated") and risk.get("acknowledged")
    high = next((x for x in get("admin", "/contracts/?limit=100") if x["status"] == "signed" and acknowledged_high(x)), None)
    if listed is None:
        sys.exit("No sanctions-listed demo vendor: run tests/e2e/showcase_screens.py sanctions first.")

    os.makedirs(OUT, exist_ok=True)
    vid_dir = os.path.join(OUT, ".video-tmp")
    shutil.rmtree(vid_dir, ignore_errors=True)
    async with async_playwright() as p:
        # Headless Chromium has no PDF viewer (the document preview would be
        # an empty box), so record in a real window, placed off-screen.
        headless = os.getenv("HEADLESS") == "1"
        browser = await p.chromium.launch(headless=headless, args=[] if headless else ["--window-position=-2400,0"])
        ctx = await browser.new_context(viewport={"width": 1280, "height": 800},
                                        record_video_dir=vid_dir, record_video_size={"width": 1280, "height": 800})
        page = await ctx.new_page()
        d = Demo(page)

        async def s1():
            await d.open("admin", "/app/control-panel", "Dropped files",
                         "0:00 · One quote dropped in ./inbox — no one clicks anything")
            c["vendor"] = f"{brand(c['rng'])} {brand(c['rng'])} Pvt Ltd"
            pdf, total = doc_pdf(c, "quote", c["vendor"], [{"name": "USB-C dock", "quantity": 2, "unit_price": 210.0}],
                                 f"QT-{c['run']}")
            name = f"quote_{c['run']}.pdf"
            with open(os.path.join(INBOX, name + ".part"), "wb") as f:
                f.write(pdf)
            os.replace(os.path.join(INBOX, name + ".part"), os.path.join(INBOX, name))
            c["file"] = name
            doc = poll(lambda: next((x for x in get("admin", "/documents/?limit=30")
                                     if x.get("original_filename") == name and x["status"] not in ("pending", "processing")), None),
                       lambda x: x is not None, timeout=150, interval=3)
            assert doc, "quote not processed within 150 s"
            c["doc"] = doc["id"]
            c["needs_review"] = bool(get("admin", f"/documents/{doc['id']}").get("needs_review"))
            await page.reload()
            await page.get_by_text(name).first.wait_for(timeout=20000)
            await d.caption(f"0:00 · {name}: scanned for viruses, stored, read and classified, vendor created")
            await page.wait_for_timeout(3000)
            return f"₹{total:,.0f} quote processed" + (" · needs review" if c["needs_review"] else "")

        async def s2():
            await d.open("finance", f"/app/documents/{c['doc']}", "Extracted",
                         "1:00 · What the AI read, and how sure it is (per-field confidence)")
            note = "no review needed"
            if c["needs_review"]:
                # Two models disagreed (usually LayoutLMv3 read the subtotal
                # as the total): automation stops and a person decides.
                await d.caption("1:00 · The two extraction models disagree on the total, so a person decides")
                await d.scroll_to("Extracted")
                await page.wait_for_timeout(3000)
                await page.get_by_role("button", name="Confirm as Correct").click()
                note = "models disagreed → finance confirmed"
            ct = poll(lambda: next((x for x in get("admin", "/contracts/?limit=50")
                                    if x.get("purchase_request_id") and x["status"] == "pending_signature"
                                    and (get("admin", f"/requests/{x['purchase_request_id']}") or {}).get("document_id") == c["doc"]), None),
                      lambda x: x is not None, timeout=90, interval=4)
            assert ct, "no contract pending signature after the review"
            c["contract"] = ct["id"]
            await d.caption("1:00 · Confirmed → request created and auto-approved (≤ ₹500 tier) → contract sent")
            await page.wait_for_timeout(2500)
            return f"{note} · contract {ct['id'][:8]} pending signature"

        async def s3():
            await d.open("finance", f"/app/contracts/{c['contract']}", "Sign now",
                         "1:45 · Finance signs in the platform — risk shown before signing")
            await page.get_by_role("button", name="Sign now").first.click()
            await page.get_by_placeholder("e.g. Jane Doe").fill("Farah Finance")
            await page.get_by_placeholder("e.g. Chief Financial Officer").fill("Finance Head")
            await page.get_by_role("button", name="Type").click()
            for box in await page.locator("input[type=checkbox]").all():
                if await box.is_visible() and not await box.is_checked():
                    await box.check()
            await page.wait_for_timeout(1000)
            await page.get_by_role("button", name="Sign & Execute Contract").click()
            await page.get_by_text("Signed", exact=False).first.wait_for(timeout=30000)
            st = get("admin", f"/contracts/{c['contract']}")["status"]
            assert st == "signed", st
            await d.caption("1:45 · Signed: SHA-256 seal + certificate; the request moves to Ordered")
            await page.wait_for_timeout(3000)
            return "signed in the UI"

        async def s4():
            await d.open("finance", f"/app/vendors/{listed['id']}", "Sanctions Screening",
                         "2:30 · Every vendor is screened against 25,000+ sanctioned companies")
            await d.scroll_to("Sanctions Screening")
            await page.get_by_role("button", name="Screen now").click()
            await page.get_by_text("Potential match", exact=False).first.wait_for(timeout=30000)
            await d.caption("2:30 · Potential match (score 100, lists named) → vendor stays High until finance reviews")
            await page.wait_for_timeout(4000)
            return "potential match shown"

        async def s5():
            if not high:
                return "skipped: no contract signed with a risk acknowledgement (run demo_scenarios.py 4)"
            await d.open("finance", f"/app/contracts/{high['id']}", "Signature certificate",
                         "3:15 · Nobody signs with an uncleared vendor without acknowledging it")
            await page.get_by_role("button", name="Signature certificate").click()
            await page.locator("text=acknowledg >> visible=true").first.wait_for(timeout=15000)
            await page.wait_for_timeout(4000)
            await page.keyboard.press("Escape")
            return "certificate records High + acknowledged"

        async def s6():
            await d.open("admin", "/app/control-panel", "Kafka log",
                         "3:45 · Nothing hidden: every event between the agents, and the ones that failed")
            await d.scroll_to("Kafka log")
            await page.wait_for_timeout(3000)
            await d.scroll_to("Failed events")
            await page.wait_for_timeout(2500)
            await d.open("admin", "/app/business-rules", "Business Rules",
                         "4:15 · 47 business rules, changed live with a justification and history")
            await page.wait_for_timeout(3500)

        print(f"5-minute demo rehearsal (run {c['run']})")
        await step("1 Quote dropped, processed unattended", 60, s1)
        await step("2 Fields, confidence, human check → contract", 60, s2)
        await step("3 Sign in the platform", 45, s3)
        await step("4 Sanctions screening", 45, s4)
        await step("5 High risk needs acknowledgement", 30, s5)
        await step("6 Kafka log, failed events, rules", 45, s6)
        await d.caption("Thank you")
        await page.wait_for_timeout(1500)
        await ctx.close()
        await browser.close()

    video = next((os.path.join(vid_dir, f) for f in os.listdir(vid_dir) if f.endswith(".webm")), None)
    target = os.path.join(OUT, "backup-recording.webm")
    if video:
        os.replace(video, target)
    shutil.rmtree(vid_dir, ignore_errors=True)

    total = sum(r[1] for r in results)
    budget = sum(r[2] for r in results)
    failed = [r for r in results if not r[3]]
    print(f"\n  {len(results) - len(failed)}/{len(results)} steps OK · {total:.0f}s of actions (budget {budget}s"
          f" = {budget // 60}:{budget % 60:02d} with talking) · recording: {os.path.relpath(target, ROOT) if video else 'none'}")
    if failed:
        print("  FAILED:", "; ".join(f"{r[0]}: {r[4]}" for r in failed))
        sys.exit(1)


def make_quote(path):
    """A fresh quote under ₹500 (new vendor and number each time, so it is
    never a duplicate) for the presenter to copy into ./inbox live."""
    c = Ctx(run=uuid.uuid4().hex[:6].upper())
    c["rng"] = random.Random(c["run"])
    vendor = f"{brand(c['rng'])} {brand(c['rng'])} Pvt Ltd"
    pdf, total = doc_pdf(c, "quote", vendor, [{"name": "USB-C dock", "quantity": 2, "unit_price": 210.0}], f"QT-{c['run']}")
    with open(path, "wb") as f:
        f.write(pdf)
    print(f"{path}: quote QT-{c['run']} from {vendor}, ₹{total:,.2f}")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--quote":
        make_quote(sys.argv[2])
    else:
        asyncio.run(main())
