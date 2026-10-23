"""docs/index.html (team) and docs/presentation.html hold every human-facing
page as a tab (scripts/docs_dashboard.py). These checks keep them whole:
every tab is in its file, every link inside a page goes to a tab or a real
file, replacing a page keeps the others, and in-page "#anchor" links are
kept inside their frame (otherwise they load the whole dashboard into it)."""
import os
import re
import shutil
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import docs_dashboard as dash  # noqa: E402

DOCS = os.path.join(ROOT, "docs")
PAGES = dash.read_pages()
FILES = {stem: pid for pid, stem, *_ in dash.PAGES}
IDS = {pid for pid, *_ in dash.PAGES}
DASH_STEMS = {f[:-5] for f, *_ in dash.DASHBOARDS.values()}


def test_every_tab_is_in_its_dashboard():
    assert set(PAGES) == IDS
    for key in dash.DASHBOARDS:
        here = dash.read_file(dash.path_of(key))
        assert set(here) == {pid for pid, *_, d, _, _ in dash.PAGES if d == key}, key
    for pid, page in PAGES.items():
        assert len(page) > 1000 and "</template>" not in page, pid


def test_docs_has_only_the_two_dashboards():
    """New human-facing pages go into a dashboard, not next to them."""
    assert sorted(f for f in os.listdir(DOCS) if f.endswith(".html")) == sorted(f for f, *_ in dash.DASHBOARDS.values())


def _tab_ok(fragment):
    head = fragment.split("/")[0]
    return head in IDS or head in dash.ALIASES or "/".join(fragment.split("/")[:2]) in dash.ALIASES


@pytest.mark.parametrize("pid", sorted(IDS))
def test_links_inside_a_page_resolve(pid):
    broken = []
    for href in re.findall(r'href="([^"]+)"', PAGES[pid]):
        if href.startswith(("#", "http://", "https://", "mailto:", "javascript:")) or "${" in href:
            continue
        m = re.match(r"^([a-z0-9-]+)\.html(?:#(.*))?$", href)
        if m:
            if m.group(1) in DASH_STEMS:
                ok = not m.group(2) or _tab_ok(m.group(2))
            else:
                ok = m.group(1) in FILES or m.group(1) in dash.ALIASES
            if not ok:
                broken.append(href)
            continue
        path = os.path.normpath(os.path.join(DOCS, href.split("#")[0]))
        if not os.path.exists(path):
            broken.append(href)
    assert not broken, broken


def test_old_tab_ids_point_at_real_tabs():
    for target, _ in dash.ALIASES.values():
        assert target in IDS


def test_replacing_a_page_keeps_the_others(tmp_path):
    copy = tmp_path / "index.html"
    shutil.copy(dash.DASHBOARD, copy)
    before = dash.read_file(str(copy))
    dash.replace_page("deploy", "<!doctype html><title>x</title><h1>new deployment page</h1>" + "." * 1000, str(copy))
    after = dash.read_file(str(copy))
    assert "new deployment page" in after["deploy"]
    assert {k: v for k, v in after.items() if k != "deploy"} == {k: v for k, v in before.items() if k != "deploy"}
    with pytest.raises(ValueError):
        dash.replace_page("deploy", "<template>x</template>", str(copy))


def test_anchor_links_stay_inside_the_frame():
    """A srcdoc frame resolves "#x" against the dashboard's address, so a
    plain in-page link loaded the whole dashboard into the frame (the
    sidebar repeated on every click). The frame script must handle them."""
    shell = dash.render("team", PAGES)
    frame_js = shell[shell.index("const LINKS"):shell.index("function savedTheme")]
    assert 'href.charAt(0) === "#"' in frame_js and "e.preventDefault()" in frame_js
    assert "location.hash = id" in frame_js


def test_outside_links_point_at_tabs_not_old_files():
    """README, CLAUDE.md and the Markdown references link to index.html#tab."""
    old = re.compile(r"(?<![\w-])(showcase|project-flow|codebase-guide|demo-script|demo-5min|risk-model|deployment|"
                     r"competitive-analysis)\.html")
    hits = []
    for base in ("README.md", "CLAUDE.md", "docs"):
        path = os.path.join(ROOT, base)
        files = [path] if os.path.isfile(path) else [os.path.join(d, f) for d, _, fs in os.walk(path) for f in fs
                                                      if f.endswith(".md")]
        for f in files:
            for n, line in enumerate(open(f, encoding="utf-8"), 1):
                if old.search(line):
                    hits.append(f"{os.path.relpath(f, ROOT)}:{n}")
    assert not hits, hits
