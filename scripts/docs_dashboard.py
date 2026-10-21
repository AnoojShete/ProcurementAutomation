"""docs/index.html: every human-facing project page in one file.

The dashboard is a bar of tabs over one frame. Each page is kept whole, as
written, inside a <template id="page-ID"> in the same file; opening a tab
renders that page in its own isolated frame (srcdoc), so pages keep their
own styles and scripts and can't clash. Links between pages, by their old
file name ("showcase.html", "risk-model.html#findings") or as dashboard links
("index.html#risk/findings"), become tab switches, and the
address bar deep-links: index.html#risk/findings opens Vendor risk at
#findings. Markdown references open in a new browser tab.

    python scripts/docs_dashboard.py list                 # the pages in docs/index.html
    python scripts/docs_dashboard.py extract risk > /tmp/risk.html   # edit a page...
    python scripts/docs_dashboard.py put risk /tmp/risk.html         # ...and put it back
    python scripts/docs_dashboard.py build docs/index.html page.html…   # (re)assemble from files

Scripts that generate a page (tests/e2e/demo_scenarios.py) call
replace_page(). tests/test_docs_dashboard.py checks the file.
"""
import html
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DASHBOARD = os.path.join(ROOT, "docs", "index.html")

# (tab id, the page's old file name, tab label, one-line description)
PAGES = [
    ("home", "index", "Overview", "Where to start and what each tab holds"),
    ("status", "project-flow", "Project status", "What is built per agent; research gap analysis"),
    ("showcase", "showcase", "Showcase", "The guided presentation for an evaluator or mentor"),
    ("demo-5min", "demo-5min", "5-minute demo", "One path through every agent, with fallbacks"),
    ("demo-script", "demo-script", "Demo script", "Eight scenarios, each checked on the running stack"),
    ("risk", "risk-model", "Vendor risk", "Scorecard, clearance, red team, evaluation"),
    ("code", "codebase-guide", "Codebase guide", "Every service, file, table, endpoint and algorithm"),
    ("deploy", "deployment", "Deployment", "Production settings, secrets, backups and restore"),
    ("market", "competitive-analysis", "Competitors", "Five commercial suites compared with the platform"),
]
_TEMPLATE = re.compile(r'<template id="page-([a-z0-9-]+)">\n?(.*?)\n?</template>', re.S)

SHELL = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Project Dashboard</title>
<meta name="description" content="Every project document of the IT Procurement Intelligence Platform in one place">
<style>
:root {{ --bg:#f4f6f9; --panel:#fff; --ink:#172033; --muted:#5d6879; --line:#d6dce5; --accent:#2563c9; }}
:root[data-theme="dark"] {{ --bg:#0e1218; --panel:#161c24; --ink:#e6ebf1; --muted:#9aa5b4; --line:#2a333f; --accent:#7aa7f2; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --bg:#0e1218; --panel:#161c24; --ink:#e6ebf1; --muted:#9aa5b4; --line:#2a333f; --accent:#7aa7f2; }} }}
* {{ box-sizing:border-box; }}
html, body {{ margin:0; height:100%; background:var(--bg); color:var(--ink); font:14px/1.4 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }}
body {{ display:flex; flex-direction:column; }}
header {{ display:flex; align-items:center; gap:12px; padding:0 12px; background:var(--panel); border-bottom:1px solid var(--line); min-height:52px; }}
.brand {{ font-weight:700; white-space:nowrap; font-size:15px; }}
.brand span {{ color:var(--muted); font-weight:500; }}
nav {{ display:flex; gap:2px; overflow-x:auto; flex:1; scrollbar-width:thin; }}
nav a {{ padding:15px 11px 13px; color:var(--muted); text-decoration:none; white-space:nowrap; border-bottom:2px solid transparent; font-weight:500; }}
nav a:hover {{ color:var(--ink); }}
nav a[aria-current="page"] {{ color:var(--ink); border-bottom-color:var(--accent); }}
.theme {{ border:1px solid var(--line); background:var(--panel); color:var(--ink); border-radius:6px; padding:5px 9px; cursor:pointer; font:inherit; }}
main {{ flex:1; position:relative; }}
main iframe {{ position:absolute; inset:0; width:100%; height:100%; border:0; background:var(--bg); }}
main iframe[hidden] {{ display:none; }}
@media (max-width:640px) {{ .brand span {{ display:none; }} nav a {{ padding:15px 8px 13px; }} }}
</style></head>
<body>
<header>
  <div class="brand">Procurement Platform <span>· project dashboard</span></div>
  <nav aria-label="Pages">{nav}</nav>
  <button class="theme" type="button" id="theme" aria-label="Switch light or dark theme">Theme</button>
</header>
<main id="main"></main>
{templates}
<script>
const PAGES = {pages_json};
const BY_FILE = Object.fromEntries(PAGES.map((p) => [p.file, p.id]));
const frames = {{}};
const LINKS = `<script>
(function () {{
  var byFile = ${{JSON.stringify(BY_FILE)}};
  document.addEventListener("click", function (e) {{
    var a = e.target.closest && e.target.closest("a[href]");
    if (!a) return;
    var href = a.getAttribute("href");
    var m = href.match(/^([a-z0-9-]+)\\\\.html(?:#(.*))?$/);
    if (m && m[1] === "index" && m[2]) {{ var parts = m[2].split("/"); e.preventDefault(); parent.openPage(parts[0], parts.slice(1).join("/")); return; }}
    if (m && byFile[m[1]]) {{ e.preventDefault(); parent.openPage(byFile[m[1]], m[2] || ""); return; }}
    if (href.charAt(0) === "#") return;
    if (!/^(javascript:|mailto:)/.test(href) && !a.target) a.target = "_blank";
  }});
  window.addEventListener("hashchange", function () {{ parent.pageHash(location.hash.slice(1)); }});
}})();
<\\/script>`;

function setTheme(t) {{
  try {{ if (t) localStorage.setItem("theme", t); }} catch (e) {{}}
  const theme = t || (function () {{ try {{ return localStorage.getItem("theme"); }} catch (e) {{ return null; }} }})();
  const apply = (doc) => {{ if (doc && doc.documentElement) {{ if (theme) doc.documentElement.setAttribute("data-theme", theme); }} }};
  apply(document);
  Object.values(frames).forEach((f) => apply(f.contentDocument));
}}
document.getElementById("theme").addEventListener("click", () => {{
  const dark = document.documentElement.getAttribute("data-theme") === "dark" ||
    (!document.documentElement.getAttribute("data-theme") && matchMedia("(prefers-color-scheme: dark)").matches);
  setTheme(dark ? "light" : "dark");
}});

let current = null;
function openPage(id, sub, fromHash) {{
  if (!PAGES.some((p) => p.id === id)) id = "home";
  if (!frames[id]) {{
    const f = document.createElement("iframe");
    f.title = PAGES.find((p) => p.id === id).label;
    f.srcdoc = "<!doctype html>" + document.getElementById("page-" + id).innerHTML + LINKS;
    f.addEventListener("load", () => {{ setTheme(); if (f.dataset.sub) jump(f, f.dataset.sub); }});
    document.getElementById("main").appendChild(f);
    frames[id] = f;
  }}
  Object.entries(frames).forEach(([k, f]) => {{ f.hidden = k !== id; }});
  document.querySelectorAll("nav a").forEach((a) => a.setAttribute("aria-current", a.dataset.id === id ? "page" : "false"));
  const f = frames[id];
  if (sub) {{ f.dataset.sub = sub; if (f.contentDocument && f.contentDocument.readyState === "complete") jump(f, sub); }}
  current = id;
  document.title = PAGES.find((p) => p.id === id).label + " · Project Dashboard";
  if (!fromHash) history.replaceState(null, "", "#" + id + (sub ? "/" + sub : ""));
}}
function jump(f, sub) {{
  delete f.dataset.sub;
  try {{ f.contentWindow.location.hash = sub; }} catch (e) {{}}
  const el = f.contentDocument && f.contentDocument.getElementById(decodeURIComponent(sub));
  if (el) el.scrollIntoView();
}}
function pageHash(sub) {{ history.replaceState(null, "", "#" + current + (sub ? "/" + sub : "")); }}
function fromLocation() {{
  const [id, ...rest] = location.hash.slice(1).split("/");
  openPage(id || "home", rest.join("/"), true);
}}
document.querySelectorAll("nav a").forEach((a) => a.addEventListener("click", (e) => {{ e.preventDefault(); openPage(a.dataset.id, ""); }}));
window.addEventListener("hashchange", fromLocation);
setTheme();
fromLocation();
</script>
</body></html>
"""


def read_pages(path: str = DASHBOARD) -> dict:
    return {m.group(1): m.group(2) for m in _TEMPLATE.finditer(open(path, encoding="utf-8").read())}


def render(pages: dict) -> str:
    known = [p for p in PAGES if p[0] in pages]
    nav = "".join(f'<a href="#{pid}" data-id="{pid}" title="{html.escape(desc)}">{html.escape(label)}</a>'
                  for pid, _, label, desc in known)
    for pid, page in pages.items():
        if "</template>" in page:
            raise ValueError(f"page {pid} contains </template>")
    templates = "\n".join(f'<template id="page-{pid}">\n{pages[pid]}\n</template>' for pid, *_ in known)
    meta = [{"id": pid, "file": stem, "label": label} for pid, stem, label, _ in known]
    return SHELL.format(nav=nav, templates=templates, pages_json=json.dumps(meta))


def write(pages: dict, path: str = DASHBOARD):
    with open(path, "w", encoding="utf-8") as f:
        f.write(render(pages))


def replace_page(page_id: str, page_html: str, path: str = DASHBOARD):
    pages = read_pages(path)
    if page_id not in {p[0] for p in PAGES}:
        raise KeyError(page_id)
    pages[page_id] = page_html.strip()
    write(pages, path)


def build(out: str, files: list[str]):
    stems = {p[1]: p[0] for p in PAGES}
    pages = {}
    for f in files:
        stem = os.path.splitext(os.path.basename(f))[0]
        if stem not in stems:
            raise SystemExit(f"{f}: not a dashboard page ({', '.join(stems)})")
        pages[stems[stem]] = open(f, encoding="utf-8").read().strip()
    write(pages, out)


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "list"
    if cmd == "list":
        pages = read_pages()
        for pid, stem, label, _ in PAGES:
            print(f"{pid:<12} {label:<16} {len(pages.get(pid, '')):>8} chars" + ("" if pid in pages else "  (missing)"))
    elif cmd == "extract":
        sys.stdout.write(read_pages()[argv[2]] + "\n")
    elif cmd == "put":
        replace_page(argv[2], open(argv[3], encoding="utf-8").read())
    elif cmd == "build":
        build(argv[2], argv[3:])
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
