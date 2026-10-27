"""Sanctions screening of vendors (FR-14).

The consolidated sanctions list from OpenSanctions (UN, EU, OFAC, UK and
others, merged; data licence CC BY-NC 4.0 — non-commercial use) is
downloaded once by an admin (`./scripts/download-sanctions.sh`, no API key)
and refreshed daily after that. Only companies and organisations are kept
(vendors are businesses; screening people against it would mostly produce
false matches). The index lives in a Docker volume, not in the repo.

A vendor's name is normalised (case, accents, punctuation, legal suffixes
such as "Pvt Ltd", "Inc", "LLC") and compared with every listed name and
alias; a score at or above the rule `risk.sanctions_match_threshold_pct`
(default 90) is a *potential match*. A potential match is a hard override
in the risk model (vendor rated High) until finance clears it with a
written justification. No list downloaded → the check is "not checked".
"""
import csv
import gzip
import io
import json
import logging
import os
import re
import time
import unicodedata
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
from rapidfuzz import fuzz, process
from sqlalchemy import select

logger = logging.getLogger(__name__)

LIST_URL = "https://data.opensanctions.org/datasets/latest/sanctions/targets.simple.csv"
LIST_DIR = os.environ.get("APP_SANCTIONS_DIR", "/app/data/sanctions")
INDEX_PATH = os.path.join(LIST_DIR, "index.json.gz")
SCHEMAS = {"Company", "Organization", "LegalEntity"}
THRESHOLD_FALLBACK = 90.0
REFRESH_SECONDS = 24 * 3600

_SUFFIXES = {
    "pvt", "private", "ltd", "limited", "llp", "llc", "inc", "incorporated", "corp", "corporation", "co",
    "company", "plc", "pjsc", "ojsc", "jsc", "oao", "zao", "ooo", "gmbh", "ag", "sa", "srl", "bv", "nv",
    "spa", "pte", "pty", "group", "holding", "holdings", "the", "and", "of",
}


def normalise(name: str) -> str:
    text = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    text = text.replace(".", "")    # "S.A." / "L.L.C." / "Pvt." → "sa" / "llc" / "pvt"
    words = re.sub(r"[^a-z0-9]+", " ", text).split()
    kept = [w for w in words if w not in _SUFFIXES]
    return " ".join(kept or words)


# ── list download and index ────────────────────────────────────────────────

def build_index(csv_text: str, version: str) -> dict:
    """Companies / organisations from the OpenSanctions targets.simple.csv."""
    entries = []
    for row in csv.DictReader(io.StringIO(csv_text)):
        if row.get("schema") not in SCHEMAS:
            continue
        names = [row.get("name") or ""] + [a for a in (row.get("aliases") or "").split(";") if a]
        entries.append({
            "id": row.get("id"), "name": row.get("name"), "names": sorted({n.strip() for n in names if n.strip()}),
            "countries": row.get("countries") or "", "datasets": row.get("dataset") or "",
        })
    return {"version": version, "source": LIST_URL, "built_at": datetime.now(timezone.utc).isoformat(), "entries": entries}


def refresh(url: str = LIST_URL) -> dict:
    """Downloads the list and writes the index. Blocking; run from a script
    or a thread."""
    with httpx.Client(timeout=300, follow_redirects=True) as client:
        r = client.get(url)
        r.raise_for_status()
    version = r.headers.get("last-modified") or datetime.now(timezone.utc).isoformat()
    index = build_index(r.text, version)
    os.makedirs(LIST_DIR, exist_ok=True)
    tmp = INDEX_PATH + ".tmp"
    with gzip.open(tmp, "wt") as f:
        json.dump(index, f)
    os.replace(tmp, INDEX_PATH)
    _cache.clear()
    logger.info(f"Sanctions list refreshed: {len(index['entries'])} companies/organisations, version {version}")
    return {"entries": len(index["entries"]), "version": version}


_cache: dict = {}


def load_index(path: str = INDEX_PATH) -> Optional[dict]:
    """The index with a flat (normalised name → entry) lookup, cached until
    the file changes. None when no list has been downloaded."""
    if not os.path.exists(path):
        return None
    mtime = os.path.getmtime(path)
    if _cache.get("path") == path and _cache.get("mtime") == mtime:
        return _cache["index"]
    with gzip.open(path, "rt") as f:
        index = json.load(f)
    flat_names, owners = [], []
    for i, e in enumerate(index["entries"]):
        for n in e["names"]:
            flat_names.append(normalise(n))
            owners.append((i, n))
    index["_flat"], index["_owners"] = flat_names, owners
    _cache.update(path=path, mtime=mtime, index=index)
    return index


def list_status() -> dict:
    index = load_index()
    if index is None:
        return {"available": False}
    return {"available": True, "version": index["version"], "entries": len(index["entries"]),
            "built_at": index["built_at"], "source": index["source"]}


def threshold() -> float:
    from shared.rules_engine import get_rule
    return float(get_rule("risk.sanctions_match_threshold_pct", fallback=THRESHOLD_FALLBACK))


def screen_name(name: str, index: dict, cutoff: Optional[float] = None) -> list[dict]:
    """Listed companies whose name or alias scores ≥ cutoff (0-100) against
    `name`, best first, one row per listed entity."""
    cutoff = threshold() if cutoff is None else cutoff
    query = normalise(name)
    if not query:
        return []
    hits = process.extract(query, index["_flat"], scorer=fuzz.token_sort_ratio, score_cutoff=cutoff, limit=20)
    best: dict = {}
    for _, score, pos in hits:
        i, alias = index["_owners"][pos]
        if i not in best or score > best[i]["score"]:
            e = index["entries"][i]
            best[i] = {"entity_id": e["id"], "listed_name": e["name"], "matched_name": alias, "score": round(score, 1),
                       "countries": e["countries"], "lists": e["datasets"]}
    return sorted(best.values(), key=lambda m: -m["score"])[:5]


# ── per-vendor screening ───────────────────────────────────────────────────

async def latest_screening(db, vendor_id: str):
    from app.models import SanctionsScreening
    return (await db.execute(
        select(SanctionsScreening).where(SanctionsScreening.vendor_id == vendor_id)
        .order_by(SanctionsScreening.screened_at.desc()).limit(1)
    )).scalars().first()


async def screen_vendor(db, vendor, screened_by: str = "system", index: Optional[dict] = None):
    """Screens one vendor and stores the result. Returns the row, or None
    when no list is available. Caller commits."""
    from app.models import SanctionsScreening
    index = index or load_index()
    if index is None:
        return None
    cut = 70.0  # Review threshold is 70.0 so fuzzy matches 70-84% trigger possible_match
    matches = screen_name(vendor.name, index, cut)
    status, justification = ("potential_match" if matches else "clear"), None
    if matches:
        # A newer list that only re-finds companies finance already cleared
        # for this vendor doesn't reopen the case.
        cleared = (await db.execute(
            select(SanctionsScreening).where(SanctionsScreening.vendor_id == str(vendor.id),
                                             SanctionsScreening.status == "cleared")
            .order_by(SanctionsScreening.screened_at.desc()).limit(1)
        )).scalars().first()
        if cleared and {m["entity_id"] for m in matches} <= {m["entity_id"] for m in cleared.matches or []}:
            status, justification = "cleared", f"Same match cleared earlier by {cleared.screened_by}: {cleared.justification}"
    row = SanctionsScreening(
        id=str(uuid.uuid4()), vendor_id=str(vendor.id), screened_at=datetime.now(timezone.utc),
        list_version=index["version"], screened_name=vendor.name,
        status=status, matches=matches, threshold=cut, screened_by=screened_by, justification=justification,
    )
    db.add(row)
    return row


async def clear_flag(db, vendor_id: str, cleared_by: str, justification: str):
    """Finance confirms a potential match is a different company. Stored as
    a new 'cleared' row for the same list version. Caller commits."""
    from app.models import SanctionsScreening
    latest = await latest_screening(db, vendor_id)
    if latest is None or latest.status != "potential_match":
        raise ValueError("There is no open sanctions match to clear for this vendor.")
    row = SanctionsScreening(
        id=str(uuid.uuid4()), vendor_id=vendor_id, screened_at=datetime.now(timezone.utc),
        list_version=latest.list_version, screened_name=latest.screened_name, status="cleared",
        matches=latest.matches, threshold=latest.threshold, screened_by=cleared_by, justification=justification.strip(),
    )
    db.add(row)
    return row


def sanctions_override_input(latest) -> Optional[bool]:
    """What the risk model's hard check receives: True = open potential
    match, False = clear or cleared, None = never screened."""
    if latest is None:
        return None
    return latest.status == "potential_match"


async def run_daily_refresh():
    """Refreshes a list that has been downloaded once, every 24 h. Never
    downloads on its own initiative if no list exists yet."""
    import asyncio
    while True:
        try:
            if os.path.exists(INDEX_PATH) and time.time() - os.path.getmtime(INDEX_PATH) > REFRESH_SECONDS:
                await asyncio.to_thread(refresh)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"Sanctions list refresh failed (keeping the old list): {e}")
        await asyncio.sleep(3600)


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["refresh"]:
        print(json.dumps(refresh()))
    else:
        print(json.dumps(list_status()))
