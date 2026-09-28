"""Browser walk-through of the UI flows that tie the agents' pages together:
back arrow, clickable lifecycle steps, approving and signing from the
lifecycle, approval-inbox routing, and the license page's open-request panel.

Needs the stack running (./run.sh + ./scripts/seed-demo-data.sh) and
Playwright, which the other e2e scripts don't:
    pip install playwright && python -m playwright install chromium
    python tests/e2e/ui_flows.py
Creates one purchase request and one reclaim request as test data.
Screenshots go to $UI_SHOTS (default: the system temp folder)."""
import asyncio, os, tempfile

import requests
from playwright.async_api import async_playwright

BASE = os.environ.get("GATEWAY", "http://localhost:8080"); API = BASE + "/api"; SHOTS = os.environ.get("UI_SHOTS", tempfile.gettempdir()) + "/"
def tok(r): return requests.post(f"{API}/auth/login", json={"email": f"{r}@demo.example.com", "password": "DemoPass123!"}).json()["data"]["access_token"]
results = []
def check(name, ok, detail=""):
    results.append(ok); print(("  ✓ " if ok else "  ✗ ") + name + ("" if ok else f"  — {detail}"))

async def main():
    req_tok, admin_tok = tok("requester"), tok("admin")
    req = requests.post(f"{API}/requests/", headers={"Authorization": f"Bearer {req_tok}"},
                        json={"request_type": "saas", "department": "Engineering", "amount": 2500, "currency": "INR",
                              "vendor_id": "11111111-1111-1111-1111-111111111111"}).json()["data"]
    rid = req["id"]
    lic = requests.get(f"{API}/inventory/", headers={"Authorization": f"Bearer {admin_tok}"}).json()["data"]["licenses"][0]
    async with async_playwright() as p:
        b = await p.chromium.launch(); pg = await (await b.new_context(viewport={"width": 1400, "height": 1000})).new_page()
        await pg.goto(BASE + "/login"); await pg.fill("#email", "admin@demo.example.com"); await pg.fill("#password", "DemoPass123!")
        await pg.click("button[type=submit]"); await pg.wait_for_url("**/app"); await pg.wait_for_timeout(800)
        check("dashboard has no back arrow", await pg.locator("button[aria-label='Go back']").count() == 0)

        await pg.goto(BASE + "/app/approvals"); await pg.wait_for_timeout(1500)
        await pg.locator(f"text={rid[:8]}").first.click(); await pg.wait_for_timeout(1500)
        check("inbox row opens the request with the Approval step open", f"/app/requests/{rid}?step=approval" in pg.url, pg.url)
        panel = pg.locator("div.border-t.bg-surface-subtle")
        check("step panel shows Approve", await panel.get_by_role("button", name="Approve").is_visible())
        await pg.screenshot(path=SHOTS + "ui-approval-step.png")

        await pg.click("button[aria-label='Go back']"); await pg.wait_for_timeout(800)
        check("back arrow returns to the inbox", pg.url.endswith("/app/approvals"), pg.url)
        await pg.go_forward(); await pg.wait_for_timeout(1500)

        await pg.get_by_role("button", name="Request Created", exact=True).click(); await pg.wait_for_timeout(300)
        check("clicking a completed step shows its info", await pg.locator("text=Raised by requester@demo.example.com").is_visible())
        await pg.get_by_role("button", name="Approval", exact=True).click(); await pg.wait_for_timeout(300)
        await panel.get_by_role("button", name="Approve").click()
        try:
            await pg.locator("text=Request approved.").first.wait_for(timeout=15000)
        except Exception:
            await pg.screenshot(path=SHOTS + "ui-approve-fail.png", full_page=True)
            print("PANEL TEXT:", (await panel.inner_text())[:600]); raise
        check("approved from the lifecycle step", True)

        await pg.wait_for_timeout(1000)
        await pg.get_by_role("button", name="Contract", exact=True).click(); await pg.wait_for_timeout(500)
        # The contract agent generates the contract when the approval event arrives.
        for _ in range(20):
            if await panel.get_by_role("button", name="Download PDF").count(): break
            await pg.wait_for_timeout(1000); await pg.reload(); await pg.wait_for_timeout(1500)  # ?step=contract survives the reload
        check("Contract step shows the contract's actions", await panel.get_by_role("button", name="Download PDF").count() > 0)
        await pg.wait_for_timeout(1500)
        await pg.get_by_role("button", name="Signature", exact=True).click(); await pg.wait_for_timeout(1000)
        dialog = pg.get_by_role("dialog")
        check("clicking Signature opens the signing dialog", await dialog.get_by_text("Sign contract").first.is_visible())
        await dialog.get_by_role("button", name="Type").click()
        await dialog.locator("input[placeholder='e.g. Jane Doe']").fill("Ada Admin")
        await dialog.locator("input[type=checkbox]").check()
        await dialog.get_by_role("button", name="Sign & Execute Contract").click()
        await pg.locator("text=Contract signed.").first.wait_for(timeout=15000)
        check("signed from the lifecycle step", True)
        await pg.wait_for_timeout(1500); await pg.screenshot(path=SHOTS + "ui-signed.png")

        await pg.goto(BASE + f"/app/licenses/{lic['id']}"); await pg.wait_for_timeout(1500)
        check("license page has a back arrow", await pg.locator("button[aria-label='Go back']").is_visible())
        requests.post(f"{API}/requests/", headers={"Authorization": f"Bearer {admin_tok}"},
                      json={"request_type": "reclaim", "department": "IT", "amount": 0, "currency": "INR",
                            "items": [{"license_id": lic["id"], "name": lic["app_name"], "quantity": 1}]})
        await pg.reload(); await pg.wait_for_timeout(2500)
        has_card = await pg.locator("text=Open reclaim request").count() > 0
        check("license page shows its open reclaim request with the approval panel", has_card)
        await pg.screenshot(path=SHOTS + "ui-license.png", full_page=True)
        await b.close()
    print(f"\nui flows: {sum(results)}/{len(results)} passed")
    raise SystemExit(0 if results and all(results) else 1)


asyncio.run(main())
