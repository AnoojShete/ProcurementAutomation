"""Regex/heuristic field extraction: vendor name, line items, quantities,
unit price, total, date, PO/invoice/quote number, plus (when present) the
vendor's bank/payment details block used by the payment-verification
governance control.

Rule-based on purpose — the synthetic templates in
data/synthetic-invoices/ are generated with matching label vocabulary/
column layouts, and the regexes here are written to tolerate the label
synonyms and both column orders those templates use, plus real OCR noise.
"""
import re
from dataclasses import dataclass, field
from datetime import date as date_cls
from typing import Optional, List, Dict, Any

from dateutil import parser as dateutil_parser

_DOC_NUMBER_PATTERNS = [
    r"\b(?:invoice|tax invoice)\s*(?:number|no\.?|#)\s*[:#]?\s*([A-Za-z0-9][A-Za-z0-9\-\/]{2,})",
    r"\bbill\s*#\s*:?\s*([A-Za-z0-9][A-Za-z0-9\-\/]{2,})",
    r"\b(?:purchase order|po)\s*(?:number|no\.?|#)\s*[:#]?\s*([A-Za-z0-9][A-Za-z0-9\-\/]{2,})",
    r"\bpo#\s*:?\s*([A-Za-z0-9][A-Za-z0-9\-\/]{2,})",
    r"\b(?:quotation|quote)\s*(?:number|no\.?|#)\s*[:#]?\s*([A-Za-z0-9][A-Za-z0-9\-\/]{2,})",
    r"\bqt#\s*:?\s*([A-Za-z0-9][A-Za-z0-9\-\/]{2,})",
]

_DATE_LABEL_PATTERN = re.compile(
    r"\b(?:invoice date|po date|quote date|date)\s*[:#]?\s*([A-Za-z0-9,\-\/ ]{6,25})",
    re.IGNORECASE,
)

_TOTAL_PATTERNS = [
    re.compile(r"\bgrand total\s*[:#]?\s*(?:INR|Rs\.?|USD|\$|₹)?\s*([\d,]+\.\d{2})", re.IGNORECASE),
    re.compile(r"\bamount due\s*[:#]?\s*(?:INR|Rs\.?|USD|\$|₹)?\s*([\d,]+\.\d{2})", re.IGNORECASE),
    re.compile(r"(?<!sub)\btotal\s*[:#]?\s*(?:INR|Rs\.?|USD|\$|₹)?\s*([\d,]+\.\d{2})", re.IGNORECASE),
]

_LINE_ITEM_PATTERNS = [
    # description ... qty ... unit_price ... line_total. Only `\s+` (not
    # `\s{2,}`) because pdfplumber's extract_text() collapses runs of
    # rendered whitespace to a single space regardless of how many blank
    # columns separated them on the page — verified empirically against
    # this service's own generated PDFs. The lazy `.+?` on desc still
    # resolves unambiguously because unit_price/line_total require a
    # decimal point + exactly 2 digits, which plain item-description text
    # never produces.
    re.compile(r"^(?P<desc>.+?)\s+(?P<qty>\d+(?:\.\d+)?)\s+(?P<unit_price>[\d,]+\.\d{2})\s+(?P<line_total>[\d,]+\.\d{2})\s*$"),
    # qty ... description ... unit_price ... line_total (alternate layout)
    re.compile(r"^(?P<qty>\d+(?:\.\d+)?)\s+(?P<desc>.+?)\s+(?P<unit_price>[\d,]+\.\d{2})\s+(?P<line_total>[\d,]+\.\d{2})\s*$"),
]

_VENDOR_BANK_ACCOUNT_PATTERN = re.compile(r"\bbank account(?: number)?\s*[:#]?\s*([A-Za-z0-9\-]{4,})", re.IGNORECASE)
_VENDOR_ROUTING_PATTERN = re.compile(r"\b(?:routing|ifsc)(?:\s*/\s*(?:routing|ifsc))?\s*code\s*[:#]?\s*([A-Za-z0-9]{4,})", re.IGNORECASE)
_VENDOR_BENEFICIARY_PATTERN = re.compile(r"\baccount name\s*[:#]?\s*(.+)", re.IGNORECASE)

_CURRENCY_MAP = [
    (re.compile(r"₹|\bINR\b|\bRs\.?\b", re.IGNORECASE), "INR"),
    (re.compile(r"\$|\bUSD\b", re.IGNORECASE), "USD"),
    (re.compile(r"\bEUR\b|€", re.IGNORECASE), "EUR"),
]


@dataclass
class ExtractedFields:
    vendor_name_raw: Optional[str] = None
    document_number: Optional[str] = None
    document_date: Optional[str] = None
    total: Optional[float] = None
    currency: Optional[str] = None
    line_items: List[Dict[str, Any]] = field(default_factory=list)
    bank_account_number: Optional[str] = None
    routing_code: Optional[str] = None
    payment_beneficiary_name: Optional[str] = None


@dataclass
class FieldConfidences:
    vendor_name: float = 0.0
    document_number: float = 0.0
    document_date: float = 0.0
    total: float = 0.0
    line_items: float = 0.0


def _first_nonempty_line(text: str) -> Optional[str]:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not re.match(r"^(invoice|purchase order|quotation|tax invoice)\b", stripped, re.IGNORECASE):
            return stripped
    return None


def _extract_vendor_name(text: str) -> (Optional[str], float):
    line = _first_nonempty_line(text)
    if not line:
        return None, 0.0
    # Reject lines that are obviously a label/value row, not a name.
    if ":" in line and len(line) < 40:
        return None, 0.2
    return line, 0.85


def _extract_document_number(text: str) -> (Optional[str], float):
    for pattern in _DOC_NUMBER_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(1).strip().rstrip(".,"), 0.95
    return None, 0.0


def _extract_document_date(text: str) -> (Optional[str], float):
    m = _DATE_LABEL_PATTERN.search(text)
    if not m:
        return None, 0.0
    raw = m.group(1).strip()
    try:
        parsed = dateutil_parser.parse(raw, fuzzy=True, dayfirst=False)
        return parsed.date().isoformat(), 0.9
    except (ValueError, OverflowError):
        return raw, 0.3


def _extract_total(text: str) -> (Optional[float], float):
    for pattern in _TOTAL_PATTERNS:
        m = pattern.search(text)
        if m:
            try:
                return float(m.group(1).replace(",", "")), 0.9
            except ValueError:
                continue
    return None, 0.0


def _extract_currency(text: str) -> Optional[str]:
    for pattern, code in _CURRENCY_MAP:
        if pattern.search(text):
            return code
    return "INR"


def _extract_line_items(text: str) -> (List[Dict[str, Any]], float):
    items = []
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        for pattern in _LINE_ITEM_PATTERNS:
            m = pattern.match(line)
            if m:
                gd = m.groupdict()
                try:
                    items.append({
                        "description": gd["desc"].strip(),
                        "quantity": float(gd["qty"]),
                        "unit_price": float(gd["unit_price"].replace(",", "")),
                        "line_total": float(gd["line_total"].replace(",", "")),
                    })
                except ValueError:
                    continue
                break
    confidence = 0.9 if items else 0.0
    return items, confidence


def _extract_vendor_bank_details(text: str) -> (Optional[str], Optional[str], Optional[str]):
    account = _VENDOR_BANK_ACCOUNT_PATTERN.search(text)
    routing = _VENDOR_ROUTING_PATTERN.search(text)
    beneficiary = _VENDOR_BENEFICIARY_PATTERN.search(text)
    return (
        account.group(1).strip() if account else None,
        routing.group(1).strip() if routing else None,
        beneficiary.group(1).strip().splitlines()[0].strip() if beneficiary else None,
    )


def extract_fields(text: str) -> (ExtractedFields, FieldConfidences):
    vendor_name, vendor_conf = _extract_vendor_name(text)
    doc_number, doc_number_conf = _extract_document_number(text)
    doc_date, doc_date_conf = _extract_document_date(text)
    total, total_conf = _extract_total(text)
    currency = _extract_currency(text)
    line_items, line_items_conf = _extract_line_items(text)
    bank_account, routing_code, beneficiary = _extract_vendor_bank_details(text)

    fields = ExtractedFields(
        vendor_name_raw=vendor_name,
        document_number=doc_number,
        document_date=doc_date,
        total=total,
        currency=currency,
        line_items=line_items,
        bank_account_number=bank_account,
        routing_code=routing_code,
        payment_beneficiary_name=beneficiary,
    )
    confidences = FieldConfidences(
        vendor_name=vendor_conf,
        document_number=doc_number_conf,
        document_date=doc_date_conf,
        total=total_conf,
        line_items=line_items_conf,
    )
    return fields, confidences
