"""The two docs dashboards: every human-facing project page, as tabs.

    docs/index.html          team workspace: overview, showcase (with the
                             5-minute demo), demo script, research, codebase
                             guide, deployment, competitors
    docs/presentation.html   for presenting: project status, vendor risk, slides

Both share one shell: a sidebar of tabs over one frame. Each page is kept
whole, as written, inside a <template id="page-ID"> in its dashboard file;
opening a tab renders that page in its own isolated frame (srcdoc), so pages
keep their own styles and scripts and can't clash. Links between pages, by
their old file name ("showcase.html", "risk-model.html#findings") or as
dashboard links ("index.html#risk/findings", "presentation.html#risk"),
become tab switches, across the two files if needed; old tab ids still work
(index.html#demo-5min opens Showcase at the 5-minute demo). In-page "#anchor"
links stay inside their frame. Markdown references open in a new browser tab.

    python scripts/docs_dashboard.py list                 # every page and its file
    python scripts/docs_dashboard.py extract risk > /tmp/risk.html   # edit a page...
    python scripts/docs_dashboard.py put risk /tmp/risk.html         # ...and put it back
    python scripts/docs_dashboard.py build                # rewrite both shells around the same pages

Scripts that generate a page (tests/e2e/demo_scenarios.py) call
replace_page(). tests/test_docs_dashboard.py checks the files.
"""
import html
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")

# dashboard key → (file in docs/, switch label, window title, first tab)
DASHBOARDS = {
    "team": ("index.html", "Team", "Team workspace", "home"),
    "present": ("presentation.html", "Present", "Presentation", "status"),
}
DASHBOARD = os.path.join(DOCS, DASHBOARDS["team"][0])

# (tab id, the page's old file name, tab label, one-line description, dashboard, icon, colour)
PAGES = [
    ("home", "index", "Overview", "Where to start", "team", "grid", "blue"),
    ("showcase", "showcase", "Showcase", "The 5-minute demo and the full walkthroughs", "team", "play", "orange"),
    ("demo-script", "demo-script", "Demo script", "Eight scenarios, each checked on the running stack", "team", "checks", "green"),
    ("research", "research", "Research", "The research gap analysis", "team", "flask", "purple"),
    ("code", "codebase-guide", "Codebase guide", "Every service, file, table, endpoint and algorithm", "team", "code", "teal"),
    ("deploy", "deployment", "Deployment", "Production settings, secrets, backups and restore", "team", "server", "grey"),
    ("market", "competitive-analysis", "Competitors", "Five commercial suites compared with the platform", "team", "chart", "pink"),
    ("status", "project-flow", "Project status", "What is built, agent by agent", "present", "flow", "blue"),
    ("risk", "risk-model", "Vendor risk", "Scorecard, clearance, red team, evaluation", "present", "shield", "pink"),
    ("slides", "slides", "Slides", "The final-review deck, slide by slide", "present", "screen", "purple"),
]
# Old tab ids and file names → (tab id, anchor inside it)
ALIASES = {
    "demo-5min": ("showcase", "five"),
    "status/research": ("research", ""),
}

ICONS = {
    "grid": '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    "play": '<circle cx="12" cy="12" r="9"/><path d="M10 8.5v7l6-3.5z"/>',
    "checks": '<path d="M4 7l2 2 3.5-3.5M4 15l2 2 3.5-3.5M13 7.5h7M13 15.5h7"/>',
    "flask": '<path d="M9 3h6M10 3v6l-5 9a2 2 0 0 0 1.7 3h10.6a2 2 0 0 0 1.7-3l-5-9V3"/><path d="M7.5 15h9"/>',
    "code": '<path d="M8 8l-4 4 4 4M16 8l4 4-4 4M13.5 5l-3 14"/>',
    "server": '<rect x="3" y="4" width="18" height="7" rx="2"/><rect x="3" y="13" width="18" height="7" rx="2"/><path d="M7 7.5h.01M7 16.5h.01"/>',
    "chart": '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
    "flow": '<rect x="3" y="3" width="7" height="6" rx="1.5"/><rect x="14" y="15" width="7" height="6" rx="1.5"/><path d="M6.5 9v4a2 2 0 0 0 2 2H14"/>',
    "shield": '<path d="M12 3l8 3v6c0 4.5-3.4 8-8 9-4.6-1-8-4.5-8-9V6z"/><path d="M9 12l2 2 4-4"/>',
    "screen": '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
    "users": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0M16 4.5a3.5 3.5 0 0 1 0 7M18 14a6 6 0 0 1 3.5 6"/>',
    "box": '<path d="M12 3l9 5v8l-9 5-9-5V8z"/><path d="M3 8l9 5 9-5M12 13v8"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "moon": '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
    "side": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/>',
}
_TEMPLATE = re.compile(r'<template id="page-([a-z0-9-]+)">\n?(.*?)\n?</template>', re.S)

SHELL = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__ · Procurement Platform</title>
<meta name="description" content="Project documents of the IT Procurement Intelligence Platform: __TITLE__">
<style>
:root { --bg:#f4f6f9; --panel:#fff; --side:#fbfcfe; --ink:#172033; --muted:#5d6879; --line:#e1e6ee; --hover:#eef2f8;
  --blue:#2563c9; --orange:#d9730d; --green:#1d8a4a; --purple:#7a3fa3; --pink:#d1336b; --teal:#0f7f86; --grey:#4b5563; }
:root[data-theme="dark"] { --bg:#0e1218; --panel:#161c24; --side:#121820; --ink:#e6ebf1; --muted:#9aa5b4; --line:#252e3a; --hover:#1c2430;
  --blue:#7aa7f2; --orange:#f2a250; --green:#4cc27f; --purple:#b98ae0; --pink:#f07aa0; --teal:#52c3c9; --grey:#a3adba; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg:#0e1218; --panel:#161c24; --side:#121820; --ink:#e6ebf1; --muted:#9aa5b4; --line:#252e3a; --hover:#1c2430;
  --blue:#7aa7f2; --orange:#f2a250; --green:#4cc27f; --purple:#b98ae0; --pink:#f07aa0; --teal:#52c3c9; --grey:#a3adba; } }
* { box-sizing:border-box; }
html, body { margin:0; height:100%; background:var(--bg); color:var(--ink); font:14px/1.4 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }
body { display:flex; }
svg.i { width:18px; height:18px; stroke:currentColor; fill:none; stroke-width:1.8; stroke-linecap:round; stroke-linejoin:round; flex:none; }
.side { width:232px; flex:none; display:flex; flex-direction:column; gap:16px; padding:16px 12px; background:var(--side); border-right:1px solid var(--line); transition:width .15s; }
.brand { display:flex; align-items:center; gap:10px; padding:2px 4px; font-weight:700; font-size:14px; white-space:nowrap; overflow:hidden; }
.mark { width:34px; height:34px; border-radius:10px; flex:none; display:grid; place-items:center; color:#fff;
  background:linear-gradient(135deg, var(--blue), var(--purple)); }
.mode { display:grid; grid-template-columns:1fr 1fr; gap:2px; background:var(--hover); border-radius:10px; padding:3px; }
.mode a { display:flex; align-items:center; justify-content:center; gap:6px; padding:6px 4px; border-radius:8px; color:var(--muted);
  text-decoration:none; font-weight:600; font-size:13px; }
.mode a[aria-current="true"] { background:var(--panel); color:var(--ink); box-shadow:0 1px 2px rgb(0 0 0 / .1); }
.mode svg.i { width:16px; height:16px; }
nav { display:flex; flex-direction:column; gap:2px; overflow-y:auto; }
nav a { --c:var(--blue); display:flex; align-items:center; gap:10px; padding:6px 8px; border-radius:10px; color:var(--ink);
  text-decoration:none; font-weight:500; white-space:nowrap; }
nav a .ic { width:30px; height:30px; flex:none; border-radius:8px; display:grid; place-items:center; color:var(--c);
  background:color-mix(in srgb, var(--c) 14%, transparent); }
nav a:hover { background:var(--hover); }
nav a[aria-current="page"] { background:color-mix(in srgb, var(--c) 11%, var(--panel)); font-weight:650; }
nav a[aria-current="page"] .ic { background:var(--c); color:var(--panel); }
.foot { margin-top:auto; display:flex; gap:6px; }
.btn { display:grid; place-items:center; width:36px; height:36px; border:1px solid var(--line); background:var(--panel); color:var(--muted);
  border-radius:9px; cursor:pointer; }
.btn:hover { color:var(--ink); }
body.slim .side { width:68px; }
body.slim .lbl, body.slim .mode .lbl { display:none; }
body.slim .mode { grid-template-columns:1fr; }
body.slim .foot { flex-direction:column; }
main { flex:1; position:relative; min-width:0; }
main iframe { position:absolute; inset:0; width:100%; height:100%; border:0; background:var(--bg); }
main iframe[hidden] { display:none; }
@media (max-width:760px) {
  body { flex-direction:column; }
  .side, body.slim .side { width:auto; flex-direction:row; align-items:center; gap:8px; padding:8px 12px; border-right:0; border-bottom:1px solid var(--line); overflow-x:auto; }
  .lbl, .brand .lbl { display:none; }
  .mode { grid-template-columns:1fr 1fr; flex:none; }
  nav { flex-direction:row; overflow:visible; }
  nav a { padding:4px; }
  .foot { margin:0 0 0 auto; flex-direction:row; }
  #slim { display:none; }
}
</style></head>
<body>
<aside class="side">
  <div class="brand"><span class="mark"><svg class="i"><use href="#i-box"/></svg></span><span class="lbl">Procurement Platform</span></div>
  <div class="mode" role="group" aria-label="Dashboard">__MODE__</div>
  <nav aria-label="Pages">__NAV__</nav>
  <div class="foot">
    <button class="btn" type="button" id="theme" aria-label="Switch light or dark theme" title="Light or dark"><svg class="i"><use href="#i-moon"/></svg></button>
    <button class="btn" type="button" id="slim" aria-label="Collapse the sidebar" title="Collapse the sidebar"><svg class="i"><use href="#i-side"/></svg></button>
  </div>
</aside>
<main id="main"></main>
<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>__ICONS__</defs></svg>
__TEMPLATES__
<script>
const DASH = __DASH__;
const DASHES = __DASHES__;
const ALL = __META__;
const ALIASES = __ALIASES__;
const PAGES = ALL.filter((p) => p.dash === DASH);
const BY_FILE = Object.fromEntries(ALL.map((p) => [p.file, p.id]));
const frames = {};
// Runs inside every page's frame: links to other pages switch tabs, and
// "#anchor" links stay in the frame (a srcdoc frame resolves "#x" against
// the dashboard's address, which would load the whole dashboard into it).
const LINKS = "<scr" + "ipt>(" + function () {
  document.addEventListener("click", function (e) {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    var a = e.target.closest && e.target.closest("a[href]");
    if (!a) return;
    var href = a.getAttribute("href");
    if (href.charAt(0) === "#") {
      e.preventDefault();
      var id = href.slice(1);
      if (!id) return;
      if (location.hash.slice(1) !== id) { location.hash = id; return; }
      var el = document.getElementById(decodeURIComponent(id));
      if (el) el.scrollIntoView({ behavior: "smooth" });
      return;
    }
    var m = href.match(/^(?:\\.\\/)?([a-z0-9-]+)\\.html(?:#(.*))?$/);
    if (m && parent.routeLink && parent.routeLink(m[1], m[2] || "")) { e.preventDefault(); return; }
    if (!/^(javascript:|mailto:)/.test(href) && !a.target) a.target = "_blank";
  });
  window.addEventListener("hashchange", function () { parent.pageHash(location.hash.slice(1)); });
} + ")();</scr" + "ipt>";

function savedTheme() { try { return localStorage.getItem("theme"); } catch (e) { return null; } }
function isDark() {
  const t = document.documentElement.getAttribute("data-theme");
  return t ? t === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
}
function setTheme(t) {
  try { if (t) localStorage.setItem("theme", t); } catch (e) {}
  const theme = t || savedTheme();
  const apply = (doc) => { if (doc && doc.documentElement && theme) doc.documentElement.setAttribute("data-theme", theme); };
  apply(document);
  Object.values(frames).forEach((f) => apply(f.contentDocument));
  document.querySelector("#theme use").setAttribute("href", isDark() ? "#i-sun" : "#i-moon");
}

function resolve(id, sub) {
  const head = (sub || "").split("/")[0];
  if (ALIASES[id + "/" + head]) { const [i, s] = ALIASES[id + "/" + head]; return [i, s || sub.split("/").slice(1).join("/")]; }
  if (ALIASES[id]) { const [i, s] = ALIASES[id]; return [i, sub || s]; }
  return [id, sub || ""];
}
function go(id, sub) {
  [id, sub] = resolve(id, sub);
  const page = ALL.find((p) => p.id === id);
  if (!page) { openPage(DASHES[DASH].home, ""); return; }
  if (page.dash !== DASH) { location.href = DASHES[page.dash].file + "#" + id + (sub ? "/" + sub : ""); return; }
  openPage(id, sub);
}
function routeLink(stem, hash) {
  const dash = Object.keys(DASHES).find((k) => DASHES[k].file === stem + ".html");
  if (dash) {
    if (!hash) { go(DASHES[dash].home, ""); return true; }
    const [id, ...rest] = hash.split("/");
    go(id, rest.join("/"));
    return true;
  }
  if (BY_FILE[stem] || ALIASES[stem]) { go(BY_FILE[stem] || stem, hash); return true; }
  return false;
}

let current = null;
function openPage(id, sub, fromHash) {
  if (!PAGES.some((p) => p.id === id)) id = DASHES[DASH].home;
  const page = PAGES.find((p) => p.id === id);
  if (!frames[id]) {
    const f = document.createElement("iframe");
    f.title = page.label;
    f.srcdoc = "<!doctype html>" + document.getElementById("page-" + id).innerHTML + LINKS;
    f.addEventListener("load", () => { setTheme(); if (f.dataset.sub) jump(f, f.dataset.sub); });
    document.getElementById("main").appendChild(f);
    frames[id] = f;
  }
  Object.entries(frames).forEach(([k, f]) => { f.hidden = k !== id; });
  document.querySelectorAll("nav a").forEach((a) => a.setAttribute("aria-current", a.dataset.id === id ? "page" : "false"));
  const f = frames[id];
  if (sub) { f.dataset.sub = sub; if (f.contentDocument && f.contentDocument.readyState === "complete") jump(f, sub); }
  current = id;
  document.title = page.label + " · " + DASHES[DASH].title;
  if (!fromHash) history.replaceState(null, "", "#" + id + (sub ? "/" + sub : ""));
}
function jump(f, sub) {
  delete f.dataset.sub;
  try { f.contentWindow.location.hash = sub; } catch (e) {}
  const el = f.contentDocument && f.contentDocument.getElementById(decodeURIComponent(sub));
  if (el) el.scrollIntoView();
}
function pageHash(sub) { history.replaceState(null, "", "#" + current + (sub ? "/" + sub : "")); }
function fromLocation() {
  const [id, ...rest] = location.hash.slice(1).split("/");
  const [rid, rsub] = resolve(id || DASHES[DASH].home, rest.join("/"));
  const page = ALL.find((p) => p.id === rid);
  if (page && page.dash !== DASH) { go(rid, rsub); return; }
  openPage(rid, rsub, rid === id && rsub === rest.join("/"));  // an old id: show the new one in the address bar
}

(function main() {
  // Opened inside another dashboard's frame (an old link): let that dashboard show the page instead.
  if (window.parent !== window) {
    try {
      if (window.parent.go) { const [id, ...rest] = location.hash.slice(1).split("/"); window.parent.go(id || DASHES[DASH].home, rest.join("/")); return; }
    } catch (e) {}
  }
  document.querySelectorAll("nav a").forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); openPage(a.dataset.id, ""); }));
  document.querySelectorAll(".mode a").forEach((a) => a.addEventListener("click", (e) => {
    if (a.dataset.dash === DASH) { e.preventDefault(); openPage(DASHES[DASH].home, ""); }
  }));
  document.getElementById("theme").addEventListener("click", () => setTheme(isDark() ? "light" : "dark"));
  const slim = (on) => { document.body.classList.toggle("slim", on); try { localStorage.setItem("dash-slim", on ? "1" : ""); } catch (e) {} };
  document.getElementById("slim").addEventListener("click", () => slim(!document.body.classList.contains("slim")));
  try { if (localStorage.getItem("dash-slim")) document.body.classList.add("slim"); } catch (e) {}
  window.addEventListener("hashchange", fromLocation);
  setTheme();
  fromLocation();
})();
</script>
</body></html>
"""


def dashboard_of(page_id: str) -> str:
    return next(p[4] for p in PAGES if p[0] == page_id)


def path_of(dash: str) -> str:
    return os.path.join(DOCS, DASHBOARDS[dash][0])


def read_file(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    return {m.group(1): m.group(2) for m in _TEMPLATE.finditer(open(path, encoding="utf-8").read())}


def read_pages(path: str = None) -> dict:
    """Every page, from both dashboards (or from one file when `path` is given)."""
    if path:
        return read_file(path)
    pages = {}
    for dash in DASHBOARDS:
        pages.update(read_file(path_of(dash)))
    return pages


def render(dash: str, pages: dict) -> str:
    known = [p for p in PAGES if p[4] == dash and p[0] in pages]
    for pid, *_ in known:
        if "</template>" in pages[pid]:
            raise ValueError(f"page {pid} contains </template>")
    nav = "".join(
        f'<a href="#{pid}" data-id="{pid}" title="{html.escape(desc)}" style="--c:var(--{colour})">'
        f'<span class="ic"><svg class="i"><use href="#i-{icon}"/></svg></span><span class="lbl">{html.escape(label)}</span></a>'
        for pid, _, label, desc, _, icon, colour in known)
    mode = "".join(
        f'<a href="{file}" data-dash="{key}" aria-current="{str(key == dash).lower()}" title="{html.escape(title)}">'
        f'<svg class="i"><use href="#i-{"users" if key == "team" else "screen"}"/></svg><span class="lbl">{label}</span></a>'
        for key, (file, label, title, _) in DASHBOARDS.items())
    icons = "".join(f'<symbol id="i-{k}" viewBox="0 0 24 24">{v}</symbol>' for k, v in ICONS.items())
    templates = "\n".join(f'<template id="page-{pid}">\n{pages[pid]}\n</template>' for pid, *_ in known)
    meta = [{"id": pid, "file": stem, "label": label, "dash": d} for pid, stem, label, _, d, *_ in PAGES]
    dashes = {k: {"file": f, "title": t, "home": h} for k, (f, _, t, h) in DASHBOARDS.items()}
    out = SHELL
    for token, value in (("__TITLE__", html.escape(DASHBOARDS[dash][2])), ("__MODE__", mode), ("__NAV__", nav),
                         ("__ICONS__", icons), ("__DASH__", json.dumps(dash)), ("__DASHES__", json.dumps(dashes)),
                         ("__META__", json.dumps(meta)), ("__ALIASES__", json.dumps(ALIASES)),
                         ("__TEMPLATES__", templates)):
        out = out.replace(token, value)
    return out


def write(pages: dict, dash: str = None, path: str = None):
    for d in ([dash] if dash else DASHBOARDS):
        with open(path or path_of(d), "w", encoding="utf-8") as f:
            f.write(render(d, pages))


def replace_page(page_id: str, page_html: str, path: str = None):
    if page_id not in {p[0] for p in PAGES}:
        raise KeyError(page_id)
    dash = dashboard_of(page_id)
    target = path or path_of(dash)
    pages = read_file(target)
    pages[page_id] = page_html.strip()
    write(pages, dash, target)


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "list"
    if cmd == "list":
        pages = read_pages()
        for pid, _, label, _, dash, *_ in PAGES:
            print(f"{pid:<12} {label:<16} {DASHBOARDS[dash][0]:<18} {len(pages.get(pid, '')):>8} chars"
                  + ("" if pid in pages else "  (missing)"))
    elif cmd == "extract":
        sys.stdout.write(read_pages()[argv[2]] + "\n")
    elif cmd == "put":
        replace_page(argv[2], open(argv[3], encoding="utf-8").read())
    elif cmd == "build":
        write(read_pages())
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
