# About these docs

This site is built with [MkDocs](https://www.mkdocs.org) and the
[Material](https://squidfunk.github.io/mkdocs-material) theme from Markdown
files in the repository.

| What | Where |
|---|---|
| Pages (Markdown) | `docs/guide/` |
| Site configuration: theme, navigation, search, code highlighting | `mkdocs.yml` |
| Diagrams and screenshots (shared with the dashboard and report) | `docs/assets/`, `docs/showcase/`, published by `scripts/mkdocs_hooks.py` |
| Pinned tool versions | `requirements-docs.txt` |
| CI build and GitHub Pages publishing | `.github/workflows/docs.yml` |

## Preview locally

Python 3.9–3.13 (the file watcher has no wheel for 3.15 yet):

```bash
python3.12 -m venv .venv-docs && . .venv-docs/bin/activate
pip install -r requirements-docs.txt
mkdocs serve          # http://127.0.0.1:8000, reloads on save
mkdocs build --strict # what CI runs; fails on a broken link → .run/docs-site/
```

## Publish to GitHub Pages

Either, from a checkout with push rights:

```bash
mkdocs gh-deploy      # builds and pushes to the gh-pages branch
```

or on GitHub: **Actions → Docs → Run workflow**, tick **deploy**. Then, once:
**Settings → Pages → Source: Deploy from a branch → `gh-pages` / root**.
The site appears at `https://<owner>.github.io/ProcurementAutomation/`.

## Regenerate diagrams and screenshots

```bash
python docs/assets/make_architecture_svg.py docs/assets/architecture.svg
python docs/assets/make_architecture_carousel.py       # the two-slide architecture (this site + Slides tab)
python scripts/render_diagrams.py                       # architecture.png, functional-flow.svg/.png
python tests/e2e/showcase_screens.py cpanel reliability # screenshots from the running stack
```

## Writing style

- Each agent page has the four parts of the standard agent template;
  project pages follow the overall documentation template.
- Sentence-case headings, short paragraphs, tables for facts, one figure per idea
  with a numbered caption (*Figure N.*).
- Names as in the app: *Control Panel*, *Pending E-Signature*, *E-Signature Complete*.
