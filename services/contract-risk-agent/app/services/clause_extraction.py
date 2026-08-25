"""Clause extraction: pull renewal type, notice period, and contract end
date out of contract text.

This is regex/keyword-rule based rather than a full NLP pipeline — the
clauses we care about (renewal type, notice period, end date) follow a
small number of standard phrasings in procurement contracts, so rules are
both explainable (good for a viva) and deterministic (good for tests).
"""
import re
from datetime import date, datetime
from typing import Optional, TypedDict

from dateutil import parser as dateutil_parser

AUTO_RENEW_PATTERNS = [
    r"automatically renew",
    r"auto-renew",
    r"shall renew automatically",
]
MANUAL_RENEW_PATTERNS = [
    r"does not automatically renew",
    r"manual(?:ly)? renew",
    r"requires written renewal",
]

NOTICE_PERIOD_PATTERNS = [
    r"notice period of (\d+)\s*days",
    r"(\d+)\s*days[’' ]*(?: prior| before| written)? notice",
    r"written notice.{0,20}?(\d+)\s*days",
    r"notice.{0,60}?(\d+)\s*days",
]

END_DATE_LABEL_PATTERNS = [
    r"(?:contract end date|expiration date|expiry date|end date)[:\s]+([A-Za-z0-9,\-/ ]{6,40})",
]


class ClauseExtractionResult(TypedDict):
    renewal_type: Optional[str]
    notice_period_days: Optional[int]
    contract_end_date: Optional[date]


def extract_clauses(contract_text: str) -> ClauseExtractionResult:
    text = contract_text or ""
    text_lower = text.lower()

    renewal_type = None
    if any(re.search(p, text_lower) for p in MANUAL_RENEW_PATTERNS):
        renewal_type = "manual"
    elif any(re.search(p, text_lower) for p in AUTO_RENEW_PATTERNS):
        renewal_type = "auto"

    notice_period_days = None
    for pattern in NOTICE_PERIOD_PATTERNS:
        match = re.search(pattern, text_lower, flags=re.DOTALL)
        if match:
            notice_period_days = int(match.group(1))
            break

    contract_end_date = None
    for pattern in END_DATE_LABEL_PATTERNS:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            raw = match.group(1).strip().rstrip(".")
            try:
                contract_end_date = dateutil_parser.parse(raw, fuzzy=True).date()
            except (ValueError, OverflowError):
                contract_end_date = None
            break

    return {
        "renewal_type": renewal_type,
        "notice_period_days": notice_period_days,
        "contract_end_date": contract_end_date,
    }
