"""Renders the project diagrams to images for the docs, the MkDocs site
and the slides.

    docs/assets/architecture.svg   -> architecture.png   (from make_architecture_svg.py)
    docs/assets/functional-flow.mmd -> functional-flow.svg + functional-flow.png

Needs Playwright with Chromium on the host (pip install -r
tests/e2e/requirements.txt && playwright install chromium) and internet
access for the Mermaid script (cdn.jsdelivr.net).

    python docs/assets/make_architecture_svg.py docs/assets/architecture.svg
    python scripts/render_diagrams.py
"""
import asyncio
import json
import os

from playwright.async_api import async_playwright

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "assets")
MERMAID = "https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"


async def svg_to_png(page, svg_path: str, png_path: str) -> None:
    with open(svg_path) as f:
        svg = f.read()
    await page.set_content(f"<html><body style='margin:0;background:#fff'>{svg}</body></html>")
    await page.locator("svg").first.screenshot(path=png_path)


async def mermaid_to_svg_png(page, mmd_path: str, svg_path: str, png_path: str) -> None:
    with open(mmd_path) as f:
        source = f.read()
    await page.set_content(f"""<html><head><script src="{MERMAID}"></script></head>
        <body style="margin:0;padding:24px;background:#fff;font-family:Helvetica,Arial,sans-serif">
        <div id="out"></div></body></html>""")
    await page.wait_for_function("window.mermaid !== undefined")
    svg = await page.evaluate(f"""async () => {{
        mermaid.initialize({{startOnLoad: false, theme: 'base', flowchart: {{htmlLabels: true, curve: 'basis'}},
                            themeVariables: {{fontFamily: 'Helvetica, Arial, sans-serif', fontSize: '15px'}}}});
        const {{svg}} = await mermaid.render('flow', {json.dumps(source)});
        document.getElementById('out').innerHTML = svg;
        // Mermaid's HTML labels contain <br> and other non-XML markup; an
        // SVG loaded through <img> must be well-formed XML or it shows
        // nothing, so serialize the parsed DOM instead of the raw string.
        return new XMLSerializer().serializeToString(document.querySelector('#out svg'));
    }}""")
    with open(svg_path, "w") as f:
        f.write(svg)
    await page.locator("#out svg").screenshot(path=png_path)


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1920, "height": 1200}, device_scale_factor=2)
        await svg_to_png(page, os.path.join(ASSETS, "architecture.svg"), os.path.join(ASSETS, "architecture.png"))
        await mermaid_to_svg_png(page, os.path.join(ASSETS, "functional-flow.mmd"),
                                 os.path.join(ASSETS, "functional-flow.svg"), os.path.join(ASSETS, "functional-flow.png"))
        await browser.close()
    print("wrote docs/assets/architecture.png, functional-flow.svg, functional-flow.png")


if __name__ == "__main__":
    asyncio.run(main())
