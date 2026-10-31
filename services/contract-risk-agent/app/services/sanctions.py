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
from functools import lru_cache
from datetime import datetime, timezone
from typing import Any, Optional, Set, Tuple

import httpx
from rapidfuzz import fuzz
from rapidfuzz.distance import JaroWinkler, Levenshtein
from sqlalchemy import select

logger = logging.getLogger(__name__)

LIST_URL = "https://data.opensanctions.org/datasets/latest/sanctions/targets.simple.csv"
LIST_DIR = os.environ.get("APP_SANCTIONS_DIR", "/app/data/sanctions")
INDEX_PATH = os.path.join(LIST_DIR, "index.json.gz")
SCHEMAS = {"Company", "Organization", "LegalEntity"}
THRESHOLD_FALLBACK = 90.0
REFRESH_SECONDS = 24 * 3600

# Rule B: Separate legal structure suffixes from generic business fillers
LEGAL_STRUCTURE_SUFFIXES = {
    "pvt", "private", "ltd", "limited", "llp", "llc", "inc", "incorporated",
    "corp", "corporation", "co", "company", "plc", "pjsc", "ojsc", "jsc",
    "oao", "zao", "ooo", "gmbh", "ag", "sa", "srl", "bv", "nv", "spa",
    "pte", "pty",
    # extra legal forms that otherwise survive as fake "distinctive" tokens
    "sal", "sarl", "sas", "kg", "oy", "ltda", "fze", "fzco", "dmcc", "bhd", "sdn", "lp",
}

GENERIC_BUSINESS_WORDS = {
    "technologies", "technology", "solutions", "systems", "services",
    "consulting", "global", "industries", "industry", "industrial", "group", "holding", "holdings",
    "international", "enterprises", "enterprise", "supplies", "supply",
    "logistics", "logistic", "trading", "trade", "products", "product",
    "materials", "material", "equipment", "hardware", "software",
    "commercial", "agency", "distributors", "distribution",
    "manufacturing", "manufacture", "import", "export",
    "marketing", "association", "associates", "associations", "medical", "marine",
    "shipping", "engineering", "construction", "management", "partners",
}

# Geographic words (india, russia, ...) are deliberately NOT generic: stripping them
# would make "Indian Railways" identical to "Russian Railways".

# Guards applied to the distinctive core of both names (see calculate_similarity)
MIN_STEM_SIMILARITY = 0.75   # normalised Levenshtein similarity of the cores
MIN_LENGTH_RATIO = 0.70      # shorter core / longer core (blocks atlas ~ atlassian)
MIN_SHARED_TOKEN_LEN = 5     # exact shared token needed for the "contained name" exception
FUZZY_GENERIC_MIN_LEN = 7    # typo-tolerant generic-word detection ("technologis")
FUZZY_GENERIC_RATIO = 88

STOPWORDS = {"the", "and", "of", "&", "it", "in", "for", "on", "at", "to", "by", "with"}

_SUFFIXES = LEGAL_STRUCTURE_SUFFIXES | GENERIC_BUSINESS_WORDS | STOPWORDS


def normalise(name: str) -> str:
    """Normalises a company name for case, accents, punctuation, and strips legal suffixes."""
    text = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    text = text.replace(".", "")    # "S.A." / "L.L.C." / "Pvt." → "sa" / "llc" / "pvt"
    words = re.sub(r"[^a-z0-9]+", " ", text).split()
    kept = [w for w in words if w not in STOPWORDS and w not in LEGAL_STRUCTURE_SUFFIXES]
    return " ".join(kept or words)


@lru_cache(maxsize=None)
def _is_generic(token: str) -> bool:
    """Generic business word, tolerating typos on long words
    ("technologis" -> "technologies")."""
    if token in GENERIC_BUSINESS_WORDS:
        return True
    if len(token) >= FUZZY_GENERIC_MIN_LEN:
        return any(len(g) >= FUZZY_GENERIC_MIN_LEN and fuzz.ratio(token, g) >= FUZZY_GENERIC_RATIO
                   for g in GENERIC_BUSINESS_WORDS)
    return False


@lru_cache(maxsize=500_000)
def extract_stems(name: str) -> Tuple[str, str]:
    """
    Extracts (distinct_stem, clean_string) implementing Rule B.
    - distinct_stem: core distinctive identifier (e.g. acronym or non-filler stem).
    - clean_string: normalized string for composite similarity comparison.
    """
    text = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    text = text.replace(".", "")
    words = re.sub(r"[^a-z0-9]+", " ", text).split()
    if not words:
        return "", ""

    # Strip stopwords and legal structure suffixes unconditionally
    words_no_legal = [w for w in words if w not in STOPWORDS and w not in LEGAL_STRUCTURE_SUFFIXES]
    if not words_no_legal:
        words_no_legal = [w for w in words if w not in STOPWORDS] or words

    # Distinctive non-filler tokens
    non_fillers = [w for w in words_no_legal if not _is_generic(w)]
    distinct_stem = "".join(non_fillers) if non_fillers else "".join(words_no_legal)

    # Rule B: DO NOT strip generic business fillers if doing so leaves a core stem of <= 3 chars
    if len("".join(non_fillers)) <= 3:
        clean_string = " ".join(words_no_legal)
    else:
        clean_string = " ".join(non_fillers)

    return distinct_stem, clean_string


def calculate_similarity(q_name: str, c_name: str, q_stem: Optional[str] = None, q_clean: Optional[str] = None) -> float:
    """
    Evaluates similarity between two entity names enforcing:
    - Rule A: Short-token guard (exact match for <= 3 chars, matching initial for 4 chars, Levenshtein <= 1 for 4-char stems).
    - Rule B: Intelligent stopword handling and stem preservation.
    - Rule C: Hybrid Jaro-Winkler (60%) + RapidFuzz Token Sort (40%) metric.
    """
    if q_stem is None or q_clean is None:
        q_stem, q_clean = extract_stems(q_name)
    c_stem, c_clean = extract_stems(c_name)

    if not q_stem or not c_stem:
        return 0.0

    # Rule A: Length-Aware Thresholding & Short-Token Guard
    # If normalized entity stem has 3 or fewer characters:
    # Similarity MUST be evaluated as an EXACT case-insensitive equality test (==).
    # If q_stem != c_stem, similarity score MUST be 0.0.
    if len(q_stem) <= 3 or len(c_stem) <= 3:
        if q_stem != c_stem:
            return 0.0

    # If normalized entity stem has 4 characters:
    # The initial characters MUST match (q_stem[0] == c_stem[0]).
    # If first letters differ, similarity MUST immediately return 0.0.
    # Additionally, 4-character stems cannot differ by more than 1 character edit (prevents false matches like ACME vs AMEN).
    if len(q_stem) == 4 or len(c_stem) == 4:
        if q_stem[0] != c_stem[0]:
            return 0.0
        if Levenshtein.distance(q_stem, c_stem) > 1:
            return 0.0

    # Rule E: core-similarity guards (stops short-vs-long and shared-generic-word hits,
    # e.g. freshworks ~ resurs, atlassian ~ atlas, hettich india ~ huawei india).
    # Compared on the distinctive core only; token order and spacing are ignored.
    q_tokens, c_tokens = q_clean.split(), c_clean.split()
    q_set, c_set = set(q_tokens), set(c_tokens)
    # One name fully contained in the other by exact, non-trivial tokens
    # ("Rosneft" vs "Rosneft Oil") stays a candidate; the composite decides.
    contained = (q_set <= c_set or c_set <= q_set) and any(len(w) >= MIN_SHARED_TOKEN_LEN for w in q_set & c_set)
    if not contained:
        q_sorted, c_sorted = "".join(sorted(q_tokens)), "".join(sorted(c_tokens))
        q_flat, c_flat = "".join(q_tokens), "".join(c_tokens)
        stem_sim = max(Levenshtein.normalized_similarity(q_sorted, c_sorted),
                       Levenshtein.normalized_similarity(q_flat, c_flat))
        len_ratio = min(len(q_flat), len(c_flat)) / max(len(q_flat), len(c_flat))
        if stem_sim < MIN_STEM_SIMILARITY or len_ratio < MIN_LENGTH_RATIO:
            return 0.0

    # Rule C: Hybrid Scoring Metric (Jaro-Winkler + Token Sort)
    jw = JaroWinkler.similarity(q_clean, c_clean) * 100.0
    ts = fuzz.token_sort_ratio(q_clean, c_clean)
    composite = round((0.6 * jw) + (0.4 * ts), 1)
    return composite


def parse_country_codes(countries_val: Any) -> Set[str]:
    """Parses country representations into a set of uppercase 2-letter country codes."""
    if not countries_val:
        return set()
    if isinstance(countries_val, (list, set, tuple)):
        raw_items = countries_val
    elif isinstance(countries_val, str):
        raw_items = re.split(r"[,;|\s]+", countries_val)
    else:
        raw_items = [str(countries_val)]
    return {c.strip().upper() for c in raw_items if c and len(c.strip()) == 2}


def classify_sanctions_match(
    best_score: float,
    vendor_country: Optional[str],
    candidate_countries: Any,
) -> Tuple[str, int]:
    """
    Rule D: Secondary Attribute Disambiguation (Country / Jurisdiction Gating).
    Returns (status, adjusted_score), where status is 'match', 'possible_match', or 'no_match'.
    """
    score = float(best_score)
    v_codes = parse_country_codes(vendor_country)
    c_codes = parse_country_codes(candidate_countries)

    has_contradiction = bool(v_codes and c_codes and not (v_codes & c_codes))
    has_match = bool(v_codes and c_codes and (v_codes & c_codes))

    if score >= 95.0:
        if has_contradiction:
            # High similarity with explicit contradiction -> manual review, do NOT hard override
            return "possible_match", 84
        else:
            return "match", int(round(score))
    elif score >= 80.0:
        if has_match:
            return "match", int(round(score))
        else:
            return "possible_match", int(round(score))
    elif score >= 70.0:
        return "possible_match", int(round(score))
    else:
        return "no_match", int(round(score))


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
    """The index with raw entries, cached until the file changes.
    None when no list has been downloaded."""
    if not os.path.exists(path):
        return None
    mtime = os.path.getmtime(path)
    if _cache.get("path") == path and _cache.get("mtime") == mtime:
        return _cache["index"]
    with gzip.open(path, "rt") as f:
        index = json.load(f)
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
    """Listed companies whose name or alias scores >= cutoff (0-100) against
    `name`, best first, one row per listed entity.
    Iterates directly over index['entries'] and their raw aliases to prevent
    prior stem stripping (Prompt 11B)."""
    cutoff = threshold() if cutoff is None else cutoff
    if not name or not name.strip():
        return []

    q_stem, q_clean = extract_stems(name)
    if not q_stem:
        return []

    best: dict = {}
    for entry in index.get("entries", []):
        entry_id = entry.get("id")
        ent_best_score = 0.0
        ent_best_alias = ""
        for alias in entry.get("names", []):
            score = calculate_similarity(name, alias, q_stem=q_stem, q_clean=q_clean)
            if score >= cutoff and score > ent_best_score:
                ent_best_score = score
                ent_best_alias = alias

        if ent_best_score >= cutoff:
            best[entry_id] = {
                "entity_id": entry_id,
                "listed_name": entry.get("name"),
                "matched_name": ent_best_alias,
                "score": round(ent_best_score, 1),
                "countries": entry.get("countries", ""),
                "lists": entry.get("datasets", ""),
            }

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
    """Refreshes a downloaded sanctions list every 24 h. Automatically
    performs an initial background download if no list exists yet."""
    import asyncio
    while True:
        try:
            needs_download = (
                not os.path.exists(INDEX_PATH)
                or (time.time() - os.path.getmtime(INDEX_PATH) > REFRESH_SECONDS)
            )
            if needs_download:
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
