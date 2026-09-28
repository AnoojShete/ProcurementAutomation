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


from shared.taxonomy.line_item_categories import categorize_line_item

_DUE_DATE_PATTERN = re.compile(
    r"\b(?:due date|payment due)\s*[:#]?\s*([A-Za-z0-9,\-\/ ]{6,25})",
    re.IGNORECASE,
)

_DELIVERY_DATE_PATTERN = re.compile(
    r"\b(?:requested delivery date|delivery date|shipping date)\s*[:#]?\s*([A-Za-z0-9,\-\/ ]{6,25})",
    re.IGNORECASE,
)

_VALID_UNTIL_PATTERN = re.compile(
    r"\b(?:valid until|valid thru|valid through|expiry date|expires?)\s*[:#]?\s*([A-Za-z0-9,\-\/ ]{6,25})",
    re.IGNORECASE,
)

_PAYMENT_TERMS_PATTERN = re.compile(
    r"\b(?:payment terms?|terms?)\s*[:#]?\s*(net\s*\d+|due on receipt|immediate|[A-Za-z0-9\s]{3,20})",
    re.IGNORECASE,
)

_TAX_PATTERN = re.compile(
    r"\b(?:tax|total tax|vat|gst|cgst\s*\+\s*sgst|igst)\s*[:#]?\s*(?:INR|Rs\.?|USD|\$|₹)?\s*([\d,]+\.\d{2})",
    re.IGNORECASE,
)

_COST_CENTER_PATTERN = re.compile(
    r"\bcost\s*center\s*[:#]?\s*([A-Za-z0-9\-_]+)",
    re.IGNORECASE,
)


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
    # Type-specific fields
    po_number: Optional[str] = None
    requested_delivery_date: Optional[str] = None
    cost_center: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    due_date: Optional[str] = None
    payment_terms: Optional[str] = None
    tax_amount: Optional[float] = None
    matched_po_number: Optional[str] = None
    quote_number: Optional[str] = None
    valid_until: Optional[str] = None
    is_binding: Optional[bool] = None

    def to_dict(self, document_type: str = "invoice") -> dict:
        d = {
            "vendor_name_raw": self.vendor_name_raw,
            "document_number": self.document_number,
            "document_date": self.document_date,
            "total": self.total,
            "currency": self.currency,
            "line_items": self.line_items,
            "bank_account_number": self.bank_account_number,
            "routing_code": self.routing_code,
            "payment_beneficiary_name": self.payment_beneficiary_name,
        }
        if document_type == "po":
            d.update({
                "po_number": self.po_number or self.document_number,
                "requested_delivery_date": self.requested_delivery_date,
                "cost_center": self.cost_center,
            })
        elif document_type == "invoice":
            d.update({
                "invoice_number": self.invoice_number or self.document_number,
                "invoice_date": self.invoice_date or self.document_date,
                "due_date": self.due_date,
                "payment_terms": self.payment_terms,
                "tax_amount": self.tax_amount,
                "matched_po_number": self.matched_po_number,
            })
        elif document_type == "quote":
            d.update({
                "quote_number": self.quote_number or self.document_number,
                "valid_until": self.valid_until,
                "is_binding": False,
            })
        return d


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


def _extract_date_by_pattern(pattern: re.Pattern, text: str) -> Optional[str]:
    m = pattern.search(text)
    if not m:
        return None
    raw = m.group(1).strip()
    try:
        parsed = dateutil_parser.parse(raw, fuzzy=True, dayfirst=False)
        return parsed.date().isoformat()
    except (ValueError, OverflowError):
        return raw


def _extract_total(text: str) -> (Optional[float], float):
    for pattern in _TOTAL_PATTERNS:
        m = pattern.search(text)
        if m:
            try:
                return float(m.group(1).replace(",", "")), 0.9
            except ValueError:
                continue
    return None, 0.0


def _extract_tax(text: str) -> Optional[float]:
    m = _TAX_PATTERN.search(text)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            return None
    return None


def _extract_cost_center(text: str) -> Optional[str]:
    m = _COST_CENTER_PATTERN.search(text)
    if m:
        return m.group(1).strip()
    return None


def _extract_payment_terms(text: str) -> Optional[str]:
    m = _PAYMENT_TERMS_PATTERN.search(text)
    if m:
        return m.group(1).strip()
    return None


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
                    desc = gd["desc"].strip()
                    category = categorize_line_item(desc)
                    items.append({
                        "description": desc,
                        "item_description": desc,
                        "quantity": float(gd["qty"]),
                        "unit_price": float(gd["unit_price"].replace(",", "")),
                        "line_total": float(gd["line_total"].replace(",", "")),
                        "category": category,
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


def extract_fields(text: str, document_type: str = "invoice") -> (ExtractedFields, FieldConfidences):
    vendor_name, vendor_conf = _extract_vendor_name(text)
    doc_number, doc_number_conf = _extract_document_number(text)
    doc_date, doc_date_conf = _extract_document_date(text)
    total, total_conf = _extract_total(text)
    currency = _extract_currency(text)
    line_items, line_items_conf = _extract_line_items(text)
    bank_account, routing_code, beneficiary = _extract_vendor_bank_details(text)

    # Type-specific extraction
    due_date = _extract_date_by_pattern(_DUE_DATE_PATTERN, text)
    delivery_date = _extract_date_by_pattern(_DELIVERY_DATE_PATTERN, text)
    valid_until = _extract_date_by_pattern(_VALID_UNTIL_PATTERN, text)
    cost_center = _extract_cost_center(text)
    payment_terms = _extract_payment_terms(text)
    tax_amount = _extract_tax(text)

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
        po_number=doc_number if document_type == "po" else None,
        requested_delivery_date=delivery_date,
        cost_center=cost_center,
        invoice_number=doc_number if document_type == "invoice" else None,
        invoice_date=doc_date if document_type == "invoice" else None,
        due_date=due_date,
        payment_terms=payment_terms,
        tax_amount=tax_amount,
        quote_number=doc_number if document_type == "quote" else None,
        valid_until=valid_until,
        is_binding=False if document_type == "quote" else None,
    )
    confidences = FieldConfidences(
        vendor_name=vendor_conf,
        document_number=doc_number_conf,
        document_date=doc_date_conf,
        total=total_conf,
        line_items=line_items_conf,
    )
    return fields, confidences

