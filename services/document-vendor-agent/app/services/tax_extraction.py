"""Reads the GST details of an Indian tax invoice (feature expansion
Phase 4): supplier and buyer GSTIN, place of supply, taxable value, CGST /
SGST / UTGST / IGST amounts and rates, HSN/SAC codes and the IRN of an
e-invoice.

Separate from field_extraction.py on purpose: those fields feed the
confidence score and the review-gate study, which must not change; this
module only feeds the tax check (tax_check.py).
"""
import re
from dataclasses import asdict, dataclass, field
from typing import Optional

# State and union-territory codes used in GSTINs and "place of supply".
STATES = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh",
    "05": "Uttarakhand", "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh",
    "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur",
    "15": "Mizoram", "16": "Tripura", "17": "Meghalaya", "18": "Assam", "19": "West Bengal",
    "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
    "26": "Dadra and Nagar Haveli and Daman and Diu", "27": "Maharashtra", "29": "Karnataka", "30": "Goa",
    "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry",
    "35": "Andaman and Nicobar Islands", "36": "Telangana", "37": "Andhra Pradesh", "38": "Ladakh",
}
_STATE_BY_NAME = {name.lower(): code for code, name in STATES.items()}

GSTIN_RE = re.compile(r"\b(\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z])\b")
_BUYER_LABEL = re.compile(r"\b(buyer|recipient|customer|bill(?:ed)?\s*to|ship(?:ped)?\s*to|consignee)\b", re.I)
_AMOUNT = r"(?:INR|Rs\.?|₹)?\s*([\d,]+\.\d{2})"
_RATE = r"(?:@\s*|\(\s*)?(\d{1,2}(?:\.\d+)?)\s*%\s*\)?"
# "CGST @ 9%: 4,500.00", "CGST (9%) 4,500.00", "IGST 18% 9,000.00" at the start of a line.
_COMPONENT = re.compile(rf"^\s*(CGST|SGST|UTGST|IGST|Cess)\b\s*(?:{_RATE})?\s*[:#]?\s*{_AMOUNT}\s*$", re.I | re.M)
_TAXABLE = re.compile(rf"\b(?:taxable\s*(?:value|amount)|assessable\s*value)\s*[:#]?\s*{_AMOUNT}", re.I)
_SUBTOTAL = re.compile(rf"\bsub\s*-?\s*total\s*[:#]?\s*{_AMOUNT}", re.I)
_PLACE = re.compile(r"\bplace\s+of\s+supply\s*[:#]?\s*([A-Za-z .&]+?)?\s*(?:\(?\s*(\d{2})\s*\)?)?\s*$", re.I | re.M)
_IRN = re.compile(r"\bIRN\s*(?:No\.?)?\s*[:#]?\s*([0-9a-f]{64})\b", re.I)
_HSN_LABEL = re.compile(r"\b(?:HSN|SAC)(?:\s*/\s*(?:HSN|SAC))?\s*(?:code)?\s*[:#]\s*(\d{4,8})\b", re.I)
_TRAILING_CODE = re.compile(r"\s(\d{4,8})$")
_REVERSE_CHARGE = re.compile(r"\breverse\s+charge\s*[:#]?\s*(yes|applicable)\b", re.I)


@dataclass
class TaxFields:
    supplier_gstin: Optional[str] = None
    buyer_gstin: Optional[str] = None
    place_of_supply: Optional[str] = None       # state code, e.g. "29"
    taxable_value: Optional[float] = None
    cgst: Optional[float] = None
    sgst: Optional[float] = None                # SGST or UTGST
    igst: Optional[float] = None
    cess: Optional[float] = None
    rates: dict = field(default_factory=dict)   # component -> [rate %, ...] as printed
    hsn_codes: list = field(default_factory=list)  # [{"code", "line_total"}], one per line where found
    irn: Optional[str] = None
    reverse_charge_marked: bool = False

    @property
    def gst_total(self) -> Optional[float]:
        parts = [v for v in (self.cgst, self.sgst, self.igst) if v is not None]
        return round(sum(parts), 2) if parts else None

    @property
    def has_breakdown(self) -> bool:
        return self.gst_total is not None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["gst_total"] = self.gst_total
        return d


def _num(raw: str) -> float:
    return float(raw.replace(",", ""))


def _gstins(text: str) -> tuple[Optional[str], Optional[str]]:
    """(supplier, buyer). A GSTIN on a line that says buyer / bill to /
    recipient is the buyer's; the first other one is the supplier's."""
    supplier = buyer = None
    lines = text.splitlines()
    for i, line in enumerate(lines):
        for m in GSTIN_RE.finditer(line.upper()):
            # The label is on the same line ("Buyer GSTIN: …") or on the
            # line above ("Bill To: Acme Corp" / "GSTIN: …").
            prev = lines[i - 1] if i else ""
            is_buyer = bool(_BUYER_LABEL.search(line[:m.start()])
                            or (_BUYER_LABEL.search(prev) and not GSTIN_RE.search(prev.upper())))
            if is_buyer:
                buyer = buyer or m.group(1)
            elif supplier is None:
                supplier = m.group(1)
            elif buyer is None:
                buyer = m.group(1)
    return supplier, buyer


def _place_of_supply(text: str) -> Optional[str]:
    m = _PLACE.search(text)
    if not m:
        return None
    if m.group(2) and m.group(2) in STATES:
        return m.group(2)
    name = (m.group(1) or "").strip().lower()
    return _STATE_BY_NAME.get(name)


def _hsn_codes(text: str, line_items: list) -> list:
    """HSN/SAC per line item: an item description ending in a 4-8 digit
    code (an HSN/SAC column read with the description), else codes printed
    with an "HSN:" / "SAC:" label."""
    codes = []
    for item in line_items or []:
        m = _TRAILING_CODE.search((item.get("description") or "").strip())
        if m:
            codes.append({"code": m.group(1), "line_total": item.get("line_total")})
    if not codes:
        codes = [{"code": c, "line_total": None} for c in _HSN_LABEL.findall(text)]
    return codes


def extract_tax_fields(text: str, line_items: Optional[list] = None) -> TaxFields:
    text = text or ""
    supplier, buyer = _gstins(text)
    out = TaxFields(supplier_gstin=supplier, buyer_gstin=buyer, place_of_supply=_place_of_supply(text))
    for m in _COMPONENT.finditer(text):
        name = m.group(1).upper()
        key = {"UTGST": "sgst", "SGST": "sgst", "CGST": "cgst", "IGST": "igst", "CESS": "cess"}[name]
        setattr(out, key, round((getattr(out, key) or 0) + _num(m.group(3)), 2))
        if m.group(2):
            out.rates.setdefault(key, []).append(float(m.group(2)))
    taxable = _TAXABLE.search(text) or _SUBTOTAL.search(text)
    if taxable:
        out.taxable_value = _num(taxable.group(1))
    out.hsn_codes = _hsn_codes(text, line_items or [])
    irn = _IRN.search(text)
    out.irn = irn.group(1).lower() if irn else None
    out.reverse_charge_marked = bool(_REVERSE_CHARGE.search(text))
    return out
