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

# Fallbacks for column layouts, where OCR reads a row of labels and then a
# row of values ("Date Issued / Invoice Number / Amount Due" then
# "26/3/2021 / INV-10012 / $1,699.48"), so the label patterns above would
# capture the next label instead of the value.
_DOC_NUMBER_TOKENS = [
    re.compile(r"\b((?:INV|BILL)[-/#]?\d[A-Za-z0-9\-\/]*)", re.IGNORECASE),
    re.compile(r"\b((?:QT|QUO)[-/#]?\d[A-Za-z0-9\-\/]*)", re.IGNORECASE),
    re.compile(r"\b(PO[-/#]?\d[A-Za-z0-9\-\/]*)", re.IGNORECASE),
]
_DATE_TOKEN = re.compile(r"\b(\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4})\b")

_DATE_LABEL_PATTERN = re.compile(
    r"\b(?:invoice date|po date|quote date|date)\s*[:#]?\s*([A-Za-z0-9,\-\/ ]{6,25})",
    re.IGNORECASE,
)

_TOTAL_PATTERNS = [
    re.compile(r"\bgrand total\s*[:#]?\s*(?:INR|Rs\.?|USD|\$|₹)?\s*([\d,]+\.\d{2})", re.IGNORECASE),
    re.compile(r"\bamount due\s*[:#]?\s*(?:INR|Rs\.?|USD|\$|₹)?\s*([\d,]+\.\d{2})", re.IGNORECASE),
    re.compile(r"(?<!sub)\btotal\s*[:#]?\s*(?:INR|Rs\.?|USD|\$|₹)?\s*([\d,]+\.\d{2})", re.IGNORECASE),
]

# Optional currency symbol in front of an amount.
_CUR = r"(?:[\$₹€£]\s?)?"

_LINE_ITEM_PATTERNS = [
    # description ... qty ... unit_price ... line_total. Only `\s+` (not
    # `\s{2,}`) because pdfplumber's extract_text() collapses runs of
    # rendered whitespace to a single space regardless of how many blank
    # columns separated them on the page — verified empirically against
    # this service's own generated PDFs. The lazy `.+?` on desc still
    # resolves unambiguously because unit_price/line_total require a
    # decimal point + exactly 2 digits, which plain item-description text
    # never produces.
    re.compile(rf"^(?P<desc>.+?)\s+(?P<qty>\d+(?:\.\d+)?)\s+{_CUR}(?P<unit_price>[\d,]+\.\d{{2}})\s+{_CUR}(?P<line_total>[\d,]+\.\d{{2}})\s*$"),
    # qty ... description ... unit_price ... line_total (alternate layout)
    re.compile(rf"^(?P<qty>\d+(?:\.\d+)?)\s+(?P<desc>.+?)\s+{_CUR}(?P<unit_price>[\d,]+\.\d{{2}})\s+{_CUR}(?P<line_total>[\d,]+\.\d{{2}})\s*$"),
    # description ... rate ... qty ... amount ("Services  $55.00  10  $550.00")
    re.compile(rf"^(?P<desc>.+?)\s+{_CUR}(?P<unit_price>[\d,]+\.\d{{2}})\s+(?P<qty>\d+(?:\.\d+)?)\s+{_CUR}(?P<line_total>[\d,]+\.\d{{2}})\s*$"),
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
    r"\b(?:tax|total tax|vat|gst|cgst\s*\+\s*sgst|igst)\s*[:#]?\s*\+?\s*(?:INR|Rs\.?|USD|\$|₹)?\s*([\d,]+\.\d{2})",
    re.IGNORECASE,
)
# An invoice that cites a purchase order is PO-backed; one that doesn't is
# a non-PO invoice (BR-3). The number must contain a digit.
_PO_REFERENCE_PATTERN = re.compile(
    r"\b(?:p\.?o\.?|purchase\s+order)\s*(?:number|no\.?|#|ref(?:erence)?)?\s*[:#]?\s*"
    r"([A-Z]{0,4}[-/]?\d[A-Z0-9\-/]{1,})",
    re.IGNORECASE,
)
_SUBTOTAL_PATTERN = re.compile(
    r"\bsub\s*-?\s*total\s*[:#]?\s*(?:INR|Rs\.?|USD|\$|₹)?\s*([\d,]+\.\d{2})", re.IGNORECASE,
)
_DISCOUNT_PATTERN = re.compile(
    r"\bdiscount\s*[:#]?\s*[-−]?\s*(?:INR|Rs\.?|USD|\$|₹)?\s*[-−]?\s*([\d,]+\.\d{2})", re.IGNORECASE,
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
    subtotal: Optional[float] = None
    discount: Optional[float] = None
    # Do the amounts add up? See _check_amounts().
    amount_check: Optional[Dict[str, Any]] = None
    matched_po_number: Optional[str] = None
    po_reference: Optional[str] = None
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
            "subtotal": self.subtotal,
            "discount": self.discount,
            "amount_check": self.amount_check,
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
                "po_reference": self.po_reference,
                "po_backed": self.po_reference is not None,
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


_CELL_SPLIT = re.compile(r"\s{2,}")
_TITLE_CELL = re.compile(r"\b(invoice|purchase order|quotation|quote|receipt|bill)\b", re.IGNORECASE)


def _value_below(text: str, label: re.Pattern) -> Optional[str]:
    """Table-style headers: a row of labels with the values on the next row
    ("Date Issued  Invoice Number  Amount Due" / "26/3/2021  INV-10012
    $1,699.48"). Cells are separated by 2+ spaces, which is how OCR rows
    are joined (see ocr._rows_to_text). Returns the cell in the same column
    as the label, or None when the rows don't line up."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    for i, line in enumerate(lines[:-1]):
        cells = _CELL_SPLIT.split(line.strip())
        for col, cell in enumerate(cells):
            if label.fullmatch(cell.strip()):
                below = _CELL_SPLIT.split(lines[i + 1].strip())
                if len(below) == len(cells):
                    return below[col].strip()
                # Value row shorter (e.g. empty leading cell): align right.
                offset = len(cells) - len(below)
                if 0 < offset <= col:
                    return below[col - offset].strip()
    return None


def _first_nonempty_line(text: str) -> Optional[str]:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or re.match(r"^(invoice|purchase order|quotation|tax invoice)\b", stripped, re.IGNORECASE):
            continue
        # A heading row like "Sample Invoice  YOUR COMPANY": skip the title.
        cells = [c for c in _CELL_SPLIT.split(stripped) if not _TITLE_CELL.search(c)]
        if cells:
            return cells[0]
    return None


def _extract_vendor_name(text: str) -> (Optional[str], float):
    line = _first_nonempty_line(text)
    if not line:
        return None, 0.0
    # Reject lines that are obviously a label/value row, not a name.
    if ":" in line and len(line) < 40:
        return None, 0.2
    return line, 0.85


_NUMBER_LABEL = re.compile(r"(?:invoice|tax invoice|bill|purchase order|po|quotation|quote)\s*(?:number|no\.?|#)", re.IGNORECASE)
_DATE_LABEL = re.compile(r"(?:invoice date|date issued|issue date|date of issue|po date|quote date|date)", re.IGNORECASE)


def _extract_document_number(text: str) -> (Optional[str], float):
    below = _value_below(text, _NUMBER_LABEL)
    if below and any(ch.isdigit() for ch in below) and " " not in below:
        return below.rstrip(".,"), 0.9
    for pattern in _DOC_NUMBER_PATTERNS:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            value = m.group(1).strip().rstrip(".,")
            if any(ch.isdigit() for ch in value):  # not the next label ("Amount")
                return value, 0.95
    for pattern in _DOC_NUMBER_TOKENS:
        m = pattern.search(text)
        if m:
            return m.group(1).rstrip(".,"), 0.6
    return None, 0.0


def _parse_date(raw: str) -> Optional[str]:
    token = _DATE_TOKEN.search(raw or "")
    if not token:
        return None
    try:
        return dateutil_parser.parse(token.group(1), dayfirst=False).date().isoformat()
    except (ValueError, OverflowError):
        return None


def _extract_document_date(text: str) -> (Optional[str], float):
    below = _parse_date(_value_below(text, _DATE_LABEL))
    if below:
        return below, 0.9
    m = _DATE_LABEL_PATTERN.search(text)
    if not m:
        return None, 0.0
    raw = m.group(1).strip()
    try:
        parsed = dateutil_parser.parse(raw, fuzzy=True, dayfirst=False)
        return parsed.date().isoformat(), 0.9
    except (ValueError, OverflowError):
        pass
    # The label is there but what follows isn't a date (a label row, see
    # _DATE_TOKEN): take the first date-shaped value in the document.
    token = _DATE_TOKEN.search(text)
    if token:
        try:
            return dateutil_parser.parse(token.group(1), dayfirst=False).date().isoformat(), 0.5
        except (ValueError, OverflowError):
            pass
    return raw, 0.3


def _extract_date_by_pattern(pattern: re.Pattern, text: str, label: Optional[re.Pattern] = None) -> Optional[str]:
    if label is not None:
        below = _parse_date(_value_below(text, label))
        if below:
            return below
    m = pattern.search(text)
    if not m:
        return None
    raw = m.group(1).strip()
    # "Due Date  90210  25/4/2021": take the date-shaped part if there is one.
    token = _parse_date(raw)
    if token:
        return token
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
        # Several layouts can match one line ("Services $55.00 10 $550.00"
        # reads as desc/qty/price/total too); prefer the reading where
        # qty x unit price = line total.
        readings = []
        for pattern in _LINE_ITEM_PATTERNS:
            m = pattern.match(line)
            if not m:
                continue
            gd = m.groupdict()
            try:
                qty = float(gd["qty"])
                unit_price = float(gd["unit_price"].replace(",", ""))
                line_total = float(gd["line_total"].replace(",", ""))
            except ValueError:
                continue
            readings.append((_close(qty * unit_price, line_total), gd["desc"].strip(), qty, unit_price, line_total))
        if not readings:
            continue
        consistent, desc, qty, unit_price, line_total = max(readings, key=lambda r: r[0])
        items.append({
            "description": desc,
            "item_description": desc,
            "quantity": qty,
            "unit_price": unit_price,
            "line_total": line_total,
            "category": categorize_line_item(desc),
            "_consistent": consistent,
        })
    if not items:
        return items, 0.0
    # Every row's arithmetic checks out: the columns were read correctly.
    confidence = 0.95 if all(i["_consistent"] for i in items) else 0.6
    for i in items:
        del i["_consistent"]
    return items, confidence


def _po_reference(text: str) -> Optional[str]:
    m = _PO_REFERENCE_PATTERN.search(text or "")
    return m.group(1).rstrip(".,").upper() if m else None


def _close(a: float, b: float) -> bool:
    """Equal to the cent, allowing for rounding on percentages/tax."""
    return abs(a - b) <= max(0.02, 0.005 * abs(b))


def _extract_amount(pattern: re.Pattern, text: str) -> Optional[float]:
    m = pattern.search(text)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _check_amounts(total, subtotal, discount, tax, line_items) -> Optional[Dict[str, Any]]:
    """Cross-checks the amounts on the document against each other:
    subtotal - discount + tax = total, and the line items add up to the
    subtotal (or the total, when there's no subtotal). Returns None when
    there's nothing to compare."""
    checks = []
    if total is not None and subtotal is not None:
        expected = subtotal - (discount or 0) + (tax or 0)
        checks.append({"check": "subtotal - discount + tax = total", "ok": _close(expected, total),
                       "expected": round(expected, 2), "found": total})
    if line_items:
        items_sum = round(sum(i["line_total"] for i in line_items), 2)
        target = subtotal if subtotal is not None else total
        if target is not None:
            checks.append({"check": "line items add up to " + ("subtotal" if subtotal is not None else "total"),
                           "ok": _close(items_sum, target), "expected": items_sum, "found": target})
    if not checks:
        return None
    return {"status": "consistent" if all(c["ok"] for c in checks) else "mismatch", "checks": checks}


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
    due_date = _extract_date_by_pattern(_DUE_DATE_PATTERN, text, re.compile(r"(?:due date|payment due)", re.IGNORECASE))
    delivery_date = _extract_date_by_pattern(_DELIVERY_DATE_PATTERN, text)
    valid_until = _extract_date_by_pattern(_VALID_UNTIL_PATTERN, text)
    cost_center = _extract_cost_center(text)
    payment_terms = _extract_payment_terms(text)
    tax_amount = _extract_tax(text)
    subtotal = _extract_amount(_SUBTOTAL_PATTERN, text)
    discount = _extract_amount(_DISCOUNT_PATTERN, text)

    # Amounts that agree with each other were almost certainly read right;
    # amounts that don't mean something was misread (or the document is
    # wrong), so the total isn't trusted.
    amount_check = _check_amounts(total, subtotal, discount, tax_amount, line_items)
    if amount_check is not None:
        if amount_check["status"] == "consistent":
            total_conf = max(total_conf, 0.98)
            if line_items:
                line_items_conf = max(line_items_conf, 0.98)
        else:
            total_conf = min(total_conf, 0.5)

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
        po_reference=_po_reference(text) if document_type == "invoice" else None,
        subtotal=subtotal,
        discount=discount,
        amount_check=amount_check,
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

