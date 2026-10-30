"""Screenshots of each agent's main pages for the report and the deck
(FR-12), saved to docs/results/screens/. Uses the items picked by
scripts/presentation_samples.py (run that first), so the pictures and the
JSON samples show the same things. Read-only.

    pip install playwright && python -m playwright install chromium
    python scripts/presentation_samples.py
    python tests/e2e/presentation_screens.py

CHROMIUM_PATH points at an existing Chromium instead of Playwright's own.
"""
import asyncio
import json
import os

from playwright.async_api import async_playwright

BASE = os.environ.get("GATEWAY", "http://localhost:8080")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SAMPLES = os.path.join(ROOT, "docs", "results", "samples")
OUT = os.path.join(ROOT, "docs", "results", "screens")


def sample_id(name, *path):
    try:
        data = json.load(open(os.path.join(SAMPLES, name)))
    except FileNotFoundError:
        return None
    for key in path:
        data = data.get(key) if isinstance(data, dict) else None
    return data


SHOTS = {   # file: (role, path, what to wait for)
    "01-documents.png": ("finance", "/app/documents", "text=Documents"),
    "02-document-detail.png": ("finance", f"/app/documents/{sample_id('document-vendor-agent.json', 'output', 'id')}", "text=Extracted"),
    "03-vendor-risk.png": ("finance", "/app/vendors/11111111-1111-1111-1111-111111111111", "text=Vendor Risk"),
    "04-vendor-risk-signals.png": ("finance", "/app/vendors/11111111-1111-1111-1111-111111111111/risk", "text=Recompute Rating"),
    "05-approval-queue.png": ("approver", "/app/approvals", "main"),
    "06-request-lifecycle.png": ("admin", f"/app/requests/{sample_id('approval-inventory-agent.json', 'output', 'id')}", "main"),
    "07-inventory-reorder.png": ("admin", "/app/inventory", "text=Reorder Suggestions"),
    "08-licence-anomaly.png": ("admin", "/app/licenses/33333333-0000-0000-0000-000000000003", "main"),
    "09-contract.png": ("finance", f"/app/contracts/{sample_id('contract-risk-agent-contract.json', 'output', 'id')}", "main"),
    "10-control-panel.png": ("admin", "/app/control-panel?section=processing", "text=Kafka log"),
    "11-business-rules.png": ("admin", "/app/business-rules", "main"),
    "12-system-health.png": ("admin", "/app/system-health", "text=Model Routing Log"),
    "13-notifications.png": ("admin", "/app/notifications", "main"),
}


async def main():
    os.makedirs(OUT, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH") or None)
        pages = {}
        for name, (role, path, wait_for) in SHOTS.items():
            if role not in pages:
                ctx = await browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme="light")
                page = await ctx.new_page()
                await page.goto(BASE + "/login")
                await page.fill("#email", f"{role}@demo.example.com")
                await page.fill("#password", "DemoPass123!")
                await page.click("button[type=submit]")
                await page.wait_for_url("**/app**")
                pages[role] = page
            page = pages[role]
            if "None" in path:
                print(f"skip {name}: no sample item (run scripts/presentation_samples.py)")
                continue
            await page.goto(BASE + path)
            try:
                await page.locator(wait_for).first.wait_for(timeout=15000)
            except Exception:
                print(f"warning: {name} — '{wait_for}' not found, taking the screenshot anyway")
            await page.wait_for_timeout(1500)
            await page.screenshot(path=os.path.join(OUT, name))
            print("saved", os.path.join("docs/results/screens", name))
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
