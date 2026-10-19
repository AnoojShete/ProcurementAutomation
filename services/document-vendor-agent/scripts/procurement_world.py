"""Procurement-world generator for the selective-automation study (RS-02).

Builds a seeded, self-consistent world: a vendor master (with GSTIN, bank
details, currency and a few look-alike names), purchase orders with line
items, and a stream of invoices against them. Each invoice carries ground
truth for its payment-critical fields and, when an error was injected,
the kind of error. Documents are rendered with synthetic_invoice_lib as
text PDFs or as scanned-style images (clean, mildly degraded, heavily
degraded), so the real extraction code reads them.

    world = build_world(seed=7, n_vendors=100, n_invoices=3000)
    data = render(world.documents[0], world.seed)   # bytes of the file

Nothing here touches a database. The evaluation (scripts/eval_selective.py)
computes the enterprise evidence against `world.vendors` / `world.pos`.

Injected business errors (one per document at most; all make the invoice
unsafe to pay automatically):
  overbill_price   a unit price above the PO's
  overbill_qty     more units than are left on the PO line
  duplicate        an earlier invoice sent again (new number, date +1..3 d)
  lookalike_vendor a near-copy of a real vendor's name, own bank details
  bank_change      the real vendor's name with different bank details
  wrong_po         cites a PO that isn't this vendor's
  gstin_mismatch   a GSTIN with a broken check digit or another vendor's
  arithmetic       the stated total doesn't equal subtotal + tax
"""
import io
import random
import string
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import List, Optional

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from scripts.synthetic_invoice_lib import _FALLBACK_ITEMS, build_image_bytes, build_pdf_bytes, render_document

GENERATOR_VERSION = "1.0"

INJECTION_RATES = {
    "overbill_price": 0.05, "overbill_qty": 0.04, "duplicate": 0.05, "lookalike_vendor": 0.04,
    "bank_change": 0.04, "wrong_po": 0.03, "gstin_mismatch": 0.03, "arithmetic": 0.03,
}
VISUAL_RATES = {"pdf": 0.55, "scan_clean": 0.25, "scan_mild": 0.12, "scan_heavy": 0.08}

_SYLLABLES = ["zen", "or", "bit", "nova", "kri", "tal", "vex", "lum", "sar", "dro", "mik", "pra", "quil",
              "tor", "hel", "ix", "ven", "cor", "ast", "rel", "gan", "sy", "mo", "fin", "tek", "ra"]
_SUFFIXES = ["Technologies Pvt Ltd", "Systems Pvt Ltd", "Infotech Ltd", "Solutions LLP", "Networks Pvt Ltd",
             "Software Inc", "Computers Pvt Ltd", "IT Services Ltd"]
_STATE_CODES = ["27", "29", "07", "33", "36", "24", "09", "19"]
_BANKS = ["HDFC", "ICIC", "SBIN", "UTIB", "KKBK", "YESB"]
_GSTIN_CHARS = string.digits + string.ascii_uppercase


def _gstin_check_char(first14: str) -> str:
    """Same modulo-36 rule as app/services/gstin_service.validate_gstin_checkdigit."""
    total, factor = 0, 1
    for ch in first14:
        product = factor * _GSTIN_CHARS.index(ch)
        total += product // 36 + product % 36
        factor = 2 if factor == 1 else 1
    return _GSTIN_CHARS[(36 - total % 36) % 36]


def _make_gstin(rng: random.Random) -> str:
    pan = "".join(rng.choice(string.ascii_uppercase) for _ in range(5)) + f"{rng.randint(0, 9999):04d}" \
        + rng.choice(string.ascii_uppercase)
    first14 = rng.choice(_STATE_CODES) + pan + str(rng.randint(1, 9)) + "Z"
    return first14 + _gstin_check_char(first14)


def _make_bank(rng: random.Random) -> dict:
    return {"account_number": str(rng.randint(10**11, 10**12 - 1)),
            "routing_code": rng.choice(_BANKS) + "0" + f"{rng.randint(0, 999999):06d}"}


def _lookalike(rng: random.Random, name: str) -> str:
    """'Zenora Systems' -> 'Zen0ra Systems' / 'Zenoora Systems' / 'Zenora Sytems'."""
    word, _, rest = name.partition(" ")
    i = rng.randint(1, len(word) - 1)
    swaps = {"o": "0", "l": "1", "i": "1", "e": "3", "a": "4", "s": "5"}
    kind = rng.choice(["swap", "double", "drop"])
    if kind == "swap" and any(c in swaps for c in word[1:].lower()):
        j = next(k for k in range(1, len(word)) if word[k].lower() in swaps)
        word = word[:j] + swaps[word[j].lower()] + word[j + 1:]
    elif kind == "double":
        word = word[:i] + word[i] + word[i:]
    else:
        word = word[:i] + word[i + 1:] if len(word) > 4 else word + "e"
    return f"{word} {rest}".strip()


@dataclass
class Vendor:
    vendor_id: str
    name: str
    gstin: str
    currency: str
    bank: dict
    weight: float  # how often it invoices (volume skew)


@dataclass
class POLine:
    description: str
    quantity: int
    unit_price: float


@dataclass
class PurchaseOrder:
    po_id: str          # 32 hex chars, like a request UUID without dashes
    vendor_id: str
    lines: List[POLine]
    amount: float       # incl. 18 % tax, like the request amounts the ledger uses
    created: str

    @property
    def reference(self) -> str:
        return "PO-" + self.po_id[:8].upper()


@dataclass
class Document:
    doc_id: str
    vendor_id: str           # vendor the invoice is for (for a look-alike: the vendor imitated)
    visual: str              # pdf | scan_clean | scan_mild | scan_heavy
    layout: str
    injection: Optional[str]
    # ground truth for the payment-critical fields, as printed on the document
    vendor_name: str
    document_number: str
    document_date: str
    total: float
    currency: str
    lines: List[str] = field(default_factory=list)   # rendered text lines
    po_id: Optional[str] = None                      # PO the invoice is against (truth)
    po_reference: Optional[str] = None               # PO reference printed, if any
    invoice_lines: List[dict] = field(default_factory=list)
    gstin: Optional[str] = None
    bank: Optional[dict] = None
    duplicate_of: Optional[str] = None

    @property
    def business_ok(self) -> bool:
        return self.injection is None


@dataclass
class World:
    seed: int
    vendors: List[Vendor]
    pos: List[PurchaseOrder]
    documents: List[Document]
    generator_version: str = GENERATOR_VERSION

    def to_dict(self) -> dict:
        return {"seed": self.seed, "generator_version": self.generator_version,
                "vendors": [asdict(v) for v in self.vendors],
                "pos": [asdict(p) | {"reference": p.reference} for p in self.pos],
                "documents": [asdict(d) for d in self.documents]}


def _vendor_names(rng: random.Random, n: int) -> List[str]:
    names, seen = [], set()
    while len(names) < n:
        word = "".join(rng.choice(_SYLLABLES) for _ in range(rng.choice([2, 2, 3]))).capitalize()
        if len(word) < 5 or word.lower() in seen:
            continue
        seen.add(word.lower())
        names.append(f"{word} {rng.choice(_SUFFIXES)}")
    return names


def _render_lines(rng: random.Random, doc: Document, vendor_name: str, items: List[dict], buyer: str,
                  arithmetic_error: bool) -> List[str]:
    lines, total = render_document(
        rng, "invoice", doc.layout, {"name": vendor_name, "currency": doc.currency}, items,
        doc.document_number, date.fromisoformat(doc.document_date), buyer,
        bank={"beneficiary": vendor_name, **doc.bank} if doc.bank else None,
    )
    if arithmetic_error:
        # Inflate only the printed total; subtotal and tax stay as computed.
        wrong = round(total * rng.uniform(1.04, 1.15), 2)
        lines = [ln.replace(f"{total:,.2f}", f"{wrong:,.2f}") if ("Total" in ln or "Amount Due" in ln) else ln
                 for ln in lines]
        total = wrong
    # GSTIN under the address, PO reference under the date.
    extra_top = [f"GSTIN: {doc.gstin}"] if doc.gstin else []
    lines = lines[:2] + extra_top + lines[2:]
    if doc.po_reference:
        at = next(i for i, ln in enumerate(lines) if ln.startswith("Invoice Date"))
        lines.insert(at + 1, f"PO Reference: {doc.po_reference}")
    doc.total = total
    return lines


def build_world(seed: int = 7, n_vendors: int = 100, n_invoices: int = 3000) -> World:
    rng = random.Random(seed)
    names = _vendor_names(rng, n_vendors)
    vendors = []
    for i, name in enumerate(names):
        vendors.append(Vendor(
            vendor_id=f"V{i:03d}", name=name, gstin=_make_gstin(rng),
            currency="USD" if rng.random() < 0.15 else "INR", bank=_make_bank(rng),
            weight=1.0 / (1 + i) ** 0.8,  # Zipf-like: a few vendors send most invoices
        ))
    rng.shuffle(vendors)  # volume rank independent of the id

    # Each vendor gets enough POs for its share of invoices (plus slack).
    total_weight = sum(v.weight for v in vendors)
    pos: List[PurchaseOrder] = []
    remaining_qty = {}  # (po_id, line index) -> units not yet invoiced
    base = date(2026, 1, 1)
    for v in vendors:
        expected = n_invoices * v.weight / total_weight
        for _ in range(max(2, int(expected / 2) + 2)):
            items = rng.sample(_FALLBACK_ITEMS, rng.randint(1, 4))
            lines = []
            for it in items:
                lo, hi = it["price_range"]
                price = round(rng.uniform(lo, hi) / (83.0 if v.currency == "USD" and lo > 500 else 1.0), 2)
                lines.append(POLine(it["name"], rng.randint(4, 40), price))
            amount = round(sum(l.quantity * l.unit_price for l in lines) * 1.18, 2)
            po = PurchaseOrder("%032x" % rng.getrandbits(128), v.vendor_id, lines, amount,
                               (base + timedelta(days=rng.randint(0, 60))).isoformat())
            pos.append(po)
            for k, l in enumerate(lines):
                remaining_qty[(po.po_id, k)] = l.quantity
    pos_by_vendor = {}
    for po in pos:
        pos_by_vendor.setdefault(po.vendor_id, []).append(po)

    kinds = list(INJECTION_RATES) + [None]
    kind_weights = list(INJECTION_RATES.values()) + [1 - sum(INJECTION_RATES.values())]
    visuals, visual_weights = list(VISUAL_RATES), list(VISUAL_RATES.values())
    docs: List[Document] = []
    issued = {v.vendor_id: 0 for v in vendors}
    day = base + timedelta(days=61)

    for n in range(n_invoices):
        if n % 12 == 11:
            day += timedelta(days=1)
        vendor = rng.choices(vendors, weights=[v.weight for v in vendors])[0]
        injection = rng.choices(kinds, weights=kind_weights)[0]
        earlier = [d for d in docs if d.vendor_id == vendor.vendor_id and d.injection is None]
        if injection == "duplicate" and not earlier:
            injection = None
        doc = Document(
            doc_id=f"D{n:05d}", vendor_id=vendor.vendor_id, visual=rng.choices(visuals, weights=visual_weights)[0],
            layout=rng.choice("ABC"), injection=injection, vendor_name=vendor.name, document_number="",
            document_date=day.isoformat(), total=0.0, currency=vendor.currency, gstin=vendor.gstin,
            bank=dict(vendor.bank) if rng.random() < 0.6 else None,
        )
        buyer = rng.choice(["Acme Corp IT Department", "Acme Corp Procurement", "Acme Corp Engineering Team"])

        if injection == "duplicate":
            orig = rng.choice(earlier[-20:])
            issued[vendor.vendor_id] += 1
            doc.document_number = f"INV-{vendor.vendor_id[1:]}-{issued[vendor.vendor_id]:04d}"
            doc.document_date = (date.fromisoformat(orig.document_date) + timedelta(days=rng.randint(1, 3))).isoformat()
            doc.layout, doc.bank, doc.po_id, doc.po_reference = orig.layout, orig.bank, orig.po_id, orig.po_reference
            doc.invoice_lines, doc.duplicate_of = orig.invoice_lines, orig.doc_id
            doc.lines = [ln.replace(orig.document_number, doc.document_number).replace(orig.document_date, doc.document_date)
                         for ln in orig.lines]
            doc.total = orig.total
            docs.append(doc)
            continue

        # Pick a PO with units left and invoice part of what's left.
        open_pos = [p for p in pos_by_vendor[vendor.vendor_id]
                    if any(remaining_qty[(p.po_id, k)] > 0 for k in range(len(p.lines)))]
        if not open_pos:  # vendor fully invoiced: give it a fresh PO
            src = rng.choice(pos_by_vendor[vendor.vendor_id])
            po = PurchaseOrder("%032x" % rng.getrandbits(128), vendor.vendor_id,
                               [POLine(l.description, l.quantity, l.unit_price) for l in src.lines], src.amount,
                               day.isoformat())
            pos.append(po)
            pos_by_vendor[vendor.vendor_id].append(po)
            for k, l in enumerate(po.lines):
                remaining_qty[(po.po_id, k)] = l.quantity
            open_pos = [po]
        po = rng.choice(open_pos)
        items = []
        for k, line in enumerate(po.lines):
            left = remaining_qty[(po.po_id, k)]
            if left <= 0 or (items and rng.random() < 0.4):
                continue
            qty = rng.randint(1, max(1, min(left, max(1, line.quantity // 3))))
            items.append({"name": line.description, "quantity": qty, "unit_price": line.unit_price, "k": k})
        if not items:
            k = next(k for k in range(len(po.lines)) if remaining_qty[(po.po_id, k)] > 0)
            items = [{"name": po.lines[k].description, "quantity": 1, "unit_price": po.lines[k].unit_price, "k": k}]

        if injection == "overbill_price":
            it = rng.choice(items)
            it["unit_price"] = round(it["unit_price"] * rng.uniform(1.03, 1.15), 2)
        elif injection == "overbill_qty":
            it = rng.choice(items)
            it["quantity"] = remaining_qty[(po.po_id, it["k"])] + rng.randint(1, 5)
        doc.po_id = po.po_id
        doc.po_reference = po.reference if rng.random() < 0.8 else None

        if injection == "lookalike_vendor":
            doc.vendor_name = _lookalike(rng, vendor.name)
            doc.bank = _make_bank(rng)
        elif injection == "bank_change":
            doc.bank = _make_bank(rng)
        elif injection == "wrong_po":
            other = rng.choice([p for p in pos if p.vendor_id != vendor.vendor_id])
            doc.po_reference = other.reference
        elif injection == "gstin_mismatch":
            if rng.random() < 0.5:
                g = vendor.gstin
                doc.gstin = g[:14] + rng.choice([c for c in _GSTIN_CHARS if c != g[14]])
            else:
                doc.gstin = rng.choice([v for v in vendors if v.vendor_id != vendor.vendor_id]).gstin

        issued[vendor.vendor_id] += 1
        doc.document_number = f"INV-{vendor.vendor_id[1:]}-{issued[vendor.vendor_id]:04d}"
        doc.invoice_lines = [{"description": it["name"], "quantity": it["quantity"], "unit_price": it["unit_price"]}
                             for it in items]
        doc.lines = _render_lines(rng, doc, doc.vendor_name, items, buyer, arithmetic_error=injection == "arithmetic")
        # Only clean invoices use up the PO: the ledger books what was approved.
        if injection is None:
            for it in items:
                remaining_qty[(po.po_id, it["k"])] -= it["quantity"]
        docs.append(doc)

    return World(seed=seed, vendors=vendors, pos=pos, documents=docs)


def _scan(rng: random.Random, lines: List[str], noise: float, blur: float, quality: int, angle: float) -> bytes:
    """A milder degradation than synthetic_invoice_lib's heavy one."""
    font = ImageFont.load_default(size=15)
    img = Image.new("RGB", (1050, max(320, 23 * (len(lines) + 3))), "white")
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        draw.text((15, 15 + 23 * i), line, font=font, fill="black")
    img = Image.blend(img, Image.effect_noise(img.size, 40).convert("RGB"), alpha=noise)
    img = img.rotate(rng.uniform(-angle, angle), expand=True, fillcolor="white").filter(ImageFilter.GaussianBlur(blur))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def render(doc: Document, seed: int) -> tuple[bytes, str, str]:
    """-> (file bytes, filename, content type). Deterministic per document."""
    rng = random.Random(f"{seed}:{doc.doc_id}")
    if doc.visual == "pdf":
        return build_pdf_bytes(doc.lines), f"{doc.doc_id}.pdf", "application/pdf"
    if doc.visual == "scan_clean":
        return build_image_bytes(rng, doc.lines, degrade=False), f"{doc.doc_id}.png", "image/png"
    if doc.visual == "scan_mild":
        return _scan(rng, doc.lines, noise=0.15, blur=0.7, quality=40, angle=1.5), f"{doc.doc_id}.jpg", "image/jpeg"
    return build_image_bytes(rng, doc.lines, degrade=True), f"{doc.doc_id}.jpg", "image/jpeg"
