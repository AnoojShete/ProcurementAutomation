"""docs/index.html holds every human-facing page as a tab (scripts/docs_dashboard.py).
These checks keep it whole: every tab is there, every link inside a page goes
to a tab or a real file, and replacing a page keeps the others."""
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


def test_every_tab_is_in_the_dashboard():
    assert set(PAGES) == IDS
    for pid, page in PAGES.items():
        assert len(page) > 1000 and "</template>" not in page, pid


def test_docs_has_one_html_file():
    """New human-facing pages go into the dashboard, not next to it."""
    assert sorted(f for f in os.listdir(DOCS) if f.endswith(".html")) == ["index.html"]


@pytest.mark.parametrize("pid", sorted(IDS))
def test_links_inside_a_page_resolve(pid):
    broken = []
    for href in re.findall(r'href="([^"]+)"', PAGES[pid]):
        if href.startswith(("#", "http://", "https://", "mailto:", "javascript:")) or "${" in href:
            continue
        m = re.match(r"^([a-z0-9-]+)\.html(?:#(.*))?$", href)
        if m:
            if m.group(1) == "index" and m.group(2):
                ok = m.group(2).split("/")[0] in IDS
            else:
                ok = m.group(1) in FILES
            if not ok:
                broken.append(href)
            continue
        path = os.path.normpath(os.path.join(DOCS, href.split("#")[0]))
        if not os.path.exists(path):
            broken.append(href)
    assert not broken, broken


def test_replacing_a_page_keeps_the_others(tmp_path):
    copy = tmp_path / "index.html"
    shutil.copy(dash.DASHBOARD, copy)
    dash.replace_page("deploy", "<!doctype html><title>x</title><h1>new deployment page</h1>" + "." * 1000, str(copy))
    after = dash.read_pages(str(copy))
    assert "new deployment page" in after["deploy"]
    assert {k: v for k, v in after.items() if k != "deploy"} == {k: v for k, v in PAGES.items() if k != "deploy"}
    with pytest.raises(ValueError):
        dash.replace_page("deploy", "<template>x</template>", str(copy))


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
