"""`.env.example` is what install.sh copies to `.env` on a fresh clone, so it
must describe the real configuration: every variable the compose files read
is listed (set or commented), and every variable it lists is read by
something. A variable compose doesn't pass on can be set in `.env` and
silently do nothing."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ("docker-compose.yml", "docker-compose.override.yml")
# Set by docker compose itself, not by .env.
BUILT_IN = {"COMPOSE_PROJECT_NAME"}


def _example_vars() -> set[str]:
    text = (ROOT / ".env.example").read_text()
    return set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", text, re.M))


def _compose_vars() -> set[str]:
    found = set()
    for name in COMPOSE:
        found |= set(re.findall(r"\$\{([A-Z][A-Z0-9_]+)", (ROOT / name).read_text()))
    return found - BUILT_IN


def test_every_compose_variable_is_in_env_example():
    missing = _compose_vars() - _example_vars()
    assert not missing, f"compose reads these but .env.example doesn't mention them: {sorted(missing)}"


def test_images_are_pinned():
    """A fresh clone must get the versions that were tested, not whatever
    `latest` means that day."""
    # minio/minio left Docker Hub, so it can't be pinned there; replacement
    # pending a decision (docs/TODO.md, REPRO-1). Remove once replaced.
    known_unpinned = {"minio/minio:latest"}
    images = []
    for name in COMPOSE:
        images += re.findall(r"^\s*image:\s*(\S+)", (ROOT / name).read_text(), re.M)
    floating = [i for i in images
                if "${" not in i and "@sha256:" not in i
                and (":" not in i.split("/")[-1] or i.endswith(":latest"))]
    assert set(floating) <= known_unpinned, f"unpinned images: {sorted(set(floating) - known_unpinned)}"


def test_every_env_example_variable_is_used():
    sources = [ROOT / n for n in COMPOSE] + [ROOT / "install.sh", ROOT / "run.sh"]
    for folder in ("services", "shared", "scripts", "frontend/src", "infra"):
        sources += [p for p in (ROOT / folder).rglob("*")
                    if p.is_file() and p.suffix in {".py", ".sh", ".ts", ".tsx", ".yml", ".yaml", ".conf"}
                    and "node_modules" not in p.parts and "tests" not in p.parts]
    corpus = "\n".join(p.read_text(errors="ignore") for p in sources)
    unused = {v for v in _example_vars() if v not in corpus}
    assert not unused, f".env.example lists variables nothing reads: {sorted(unused)}"
