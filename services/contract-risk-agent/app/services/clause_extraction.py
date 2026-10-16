"""Clause extraction: pull renewal type, notice period, and contract end
date out of contract text.

`extract_clauses` is the rule-based extractor — regex/keyword rules for the
standard phrasings in procurement contracts; explainable and deterministic.
It is the fallback since FR-13: the primary is Legal-BERT (clause_model.py),
which finds the passage for each clause; the `*_from` parsers below turn
those passages into values.
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
    # \s, not a space: the templates wrap lines ("15 days\n   notice").
    r"(\d+)\s*days[’'\s]*(?:(?:prior|before|written)\s+)?notice",
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


# ── values from a passage the clause model found (FR-13) ──────────────────

_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty-five": 45, "forty five": 45,
    "forty": 40, "sixty": 60, "ninety": 90, "one hundred twenty": 120, "one hundred and twenty": 120,
    "one hundred eighty": 180, "one hundred and eighty": 180,
}
_UNIT_DAYS = {"day": 1, "business day": 1, "week": 7, "month": 30, "year": 365}
_NOTICE_AMOUNT = re.compile(
    r"(?:(\d+)|\(\s*(\d+)\s*\)|(" + "|".join(sorted(map(re.escape, _NUMBER_WORDS), key=len, reverse=True)) + r"))"
    r"(?:\s*\(\s*\d+\s*\))?[\s-]*(business day|day|week|month|year)s?(?:'|’)?",
    re.IGNORECASE,
)


def renewal_type_from(passage: Optional[str]) -> Optional[str]:
    """"auto" for an automatic extension, "manual" for any other renewal
    wording, None without a passage."""
    if not passage:
        return None
    text = passage.lower()
    if any(re.search(p, text) for p in MANUAL_RENEW_PATTERNS) or re.search(r"\b(?:not|no)\b.{0,20}automatic", text):
        return "manual"
    if any(re.search(p, text) for p in AUTO_RENEW_PATTERNS) or re.search(r"automatic(?:ally)?\b", text):
        return "auto"
    return "manual"


def notice_days_from(passage: Optional[str]) -> Optional[int]:
    """The notice period in days ("sixty (60) days", "90 days", "three
    months" → 90); the amount nearest the word "notice" when there are
    several. None when the passage doesn't mention notice — "renews for
    one year" is a term, not a notice period."""
    notice = [i.start() for i in re.finditer(r"notice|notif", passage or "", re.IGNORECASE)]
    if not notice:
        return None
    found = []
    for m in _NOTICE_AMOUNT.finditer(passage):
        digits = m.group(1) or m.group(2)
        n = int(digits) if digits else _NUMBER_WORDS[m.group(3).lower()]
        found.append((m.start(), n * _UNIT_DAYS[m.group(4).lower()]))
    if not found:
        return None
    return min(found, key=lambda f: min(abs(f[0] - n) for n in notice))[1]


_DATE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}\b"
    r"|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}\b"
    r"|\b\d{1,2}(?:st|nd|rd|th)?\s+(?:day\s+of\s+)?(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*,?\s+\d{4}\b",
    re.IGNORECASE,
)


def end_date_from(passage: Optional[str]) -> Optional[date]:
    """An explicit date in the passage (the last one — "from 1 April 2024
    until 31 March 2027"); None when the term is relative ("five years from
    the Effective Date")."""
    if not passage:
        return None
    dates = _DATE.findall(passage)
    for raw in reversed(dates):
        try:
            return dateutil_parser.parse(raw.replace("day of", ""), fuzzy=True).date()
        except (ValueError, OverflowError):
            continue
    return None
