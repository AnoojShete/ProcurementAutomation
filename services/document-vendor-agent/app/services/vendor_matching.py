"""Vendor name normalization + fuzzy dedup against the shared `vendors`
table, before ever creating a new vendor row.
"""
import re
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Optional, List

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import load_vendor_matching_config
from app.models import Vendor

_PUNCT_RE = re.compile(r"[^\w\s]")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_vendor_name(raw_name: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace, and drop trailing
    corporate suffixes (Inc/Ltd/LLC/Pvt/...) so 'Acme Corp, Inc.' and
    'ACME CORP INC' normalize to the same string."""
    if not raw_name:
        return ""
    suffixes = [s.lower() for s in load_vendor_matching_config().get("suffixes", [])]
    name = raw_name.strip().lower()
    name = _PUNCT_RE.sub(" ", name)
    name = _WHITESPACE_RE.sub(" ", name).strip()

    tokens = name.split(" ")
    changed = True
    while changed and tokens:
        changed = False
        # multi-word suffixes (e.g. "private limited") checked first
        for suffix in sorted(suffixes, key=lambda s: -len(s.split())):
            suffix_tokens = suffix.split(" ")
            n = len(suffix_tokens)
            if n and tokens[-n:] == suffix_tokens:
                tokens = tokens[:-n]
                changed = True
                break
    return " ".join(tokens).strip()


@dataclass
class VendorMatchResult:
    vendor: Vendor
    match_type: str  # "existing" | "new"
    match_confidence: float
    # For a new vendor: the most similar existing vendor and its 0-100
    # score, so callers can spot lookalike names (e.g. "Del1 Technologies").
    closest_existing: Optional[Vendor] = None
    closest_score: float = 0.0


async def find_or_create_vendor(db: AsyncSession, raw_vendor_name: str, session_factory=None) -> VendorMatchResult:
    normalized = normalize_vendor_name(raw_vendor_name)
    threshold = load_vendor_matching_config().get("fuzzy_match_threshold", 88)

    result = await db.execute(select(Vendor))
    candidates: List[Vendor] = list(result.scalars().all())

    best_vendor: Optional[Vendor] = None
    best_score = 0.0
    for candidate in candidates:
        candidate_normalized = candidate.normalized_name or normalize_vendor_name(candidate.name)
        score = fuzz.token_sort_ratio(normalized, candidate_normalized)
        if score > best_score:
            best_score = score
            best_vendor = candidate

    if best_vendor is not None and best_score >= threshold:
        return VendorMatchResult(vendor=best_vendor, match_type="existing", match_confidence=round(best_score / 100, 3))

    new_vendor = Vendor(
        id=str(uuid.uuid4()),
        name=raw_vendor_name.strip() if raw_vendor_name else "Unknown Vendor",
        normalized_name=normalized,
        status="active",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    # Committed in its own transaction, not the caller's: later in the
    # pipeline approval-inventory-agent stores an invoice match pointing at
    # this vendor (fk_invoice_matches_vendor), and it can't see rows from a
    # transaction that hasn't committed yet. A retry then finds this vendor
    # instead of creating another one.
    if session_factory is None:
        from app.database import async_session_factory as session_factory
    async with session_factory() as vendor_session:
        vendor_session.add(new_vendor)
        await vendor_session.commit()
    new_vendor = await db.get(Vendor, new_vendor.id)
    return VendorMatchResult(
        vendor=new_vendor, match_type="new", match_confidence=1.0,
        closest_existing=best_vendor, closest_score=best_score,
    )
