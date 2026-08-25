"""Duplicate-invoice detection: fuzzy-match a newly extracted invoice
against existing invoices for the same vendor on (amount within
tolerance, date within window), rather than silently accepting it.
"""
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import load_duplicate_detection_config
from app.models import Document


@dataclass
class DuplicateCheckResult:
    is_duplicate: bool
    duplicate_of_document_id: Optional[str] = None
    reason: Optional[str] = None


async def check_duplicate_invoice(
    db: AsyncSession, vendor_id: str, total: Optional[float], document_date_str: Optional[str],
    document_number: Optional[str], exclude_document_id: Optional[str] = None,
) -> DuplicateCheckResult:
    if not vendor_id or total is None:
        return DuplicateCheckResult(is_duplicate=False)

    cfg = load_duplicate_detection_config()
    amount_tolerance_pct = cfg.get("amount_tolerance_pct", 0.01)
    date_window_days = cfg.get("date_window_days", 5)
    doc_number_threshold = cfg.get("document_number_fuzzy_threshold", 85)

    parsed_date: Optional[date] = None
    if document_date_str:
        try:
            parsed_date = date.fromisoformat(document_date_str)
        except ValueError:
            parsed_date = None

    query = select(Document).where(
        Document.vendor_id == vendor_id,
        Document.document_type == "invoice",
    )
    result = await db.execute(query)
    candidates = list(result.scalars().all())

    tolerance = max(total * amount_tolerance_pct, 0.01)
    for candidate in candidates:
        if exclude_document_id and candidate.id == exclude_document_id:
            continue
        if candidate.total is None:
            continue
        if abs(float(candidate.total) - total) > tolerance:
            continue

        if parsed_date and candidate.document_date:
            if abs((candidate.document_date - parsed_date).days) > date_window_days:
                continue
        # If either side is missing a date, don't let that alone rule out
        # a duplicate — amount match on the same vendor is already a
        # strong signal worth a human's attention.

        number_similar = True
        if document_number and candidate.document_number:
            number_similar = fuzz.ratio(document_number, candidate.document_number) >= doc_number_threshold

        if number_similar:
            return DuplicateCheckResult(
                is_duplicate=True,
                duplicate_of_document_id=candidate.id,
                reason=(
                    f"same vendor, amount within tolerance ({total} vs {candidate.total}), "
                    f"date within {date_window_days}d window"
                ),
            )

    return DuplicateCheckResult(is_duplicate=False)
