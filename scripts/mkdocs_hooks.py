"""MkDocs hook (mkdocs.yml `hooks:`): adds docs/assets and docs/showcase to
the site, so the pages in docs/guide can show the same diagrams and
screenshots the dashboard and the report use, without copying them.

A page links to them as if they sat next to docs/guide:
`![Architecture](assets/architecture.png)` from docs/guide/index.md,
`../assets/architecture.png` from a page one folder down."""
import os

from mkdocs.structure.files import File

DOCS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")
SHARED = ("assets", "showcase")
KEEP = (".png", ".svg", ".jpg", ".jpeg", ".webp", ".gif")


def on_files(files, config):
    for folder in SHARED:
        for dirpath, _, names in os.walk(os.path.join(DOCS, folder)):
            for name in sorted(names):
                if name.lower().endswith(KEEP):
                    rel = os.path.relpath(os.path.join(dirpath, name), DOCS)
                    files.append(File(rel, DOCS, config["site_dir"], config["use_directory_urls"]))
    return files
