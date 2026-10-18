"""Labelled documents for training and evaluating the document classifier
(FR-29): invoice, po, quote and other.

The committed 105-row dataset is templated text that always carries a
title, so any classifier scores ~100 % on it. This corpus is harder, the
way real intake is:
  - invoices / POs / quotes from the platform's own generator
    (scripts/synthetic_invoice_lib.py, three layouts, real vendor/item
    catalogue), each in three variants:
        clean      — as rendered
        ocr_noise  — 4-10 % of characters garbled the way OCR does
                     (0/O, 1/l, rn/m, dropped spaces)
        no_title   — the title line ("TAX INVOICE", "PURCHASE ORDER",
                     "QUOTATION") missing, as when the header is a logo
  - "other": delivery notes, statements of account, payment receipts,
    cover letters, credit notes — paperwork that must not be forced into
    one of the three types.
Seeded, so the split is reproducible.
"""
import os
import random
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "scripts"))

from synthetic_invoice_lib import _BUYERS as _GEN_BUYERS, _pick_bank, render_document  # noqa: E402
from datetime import date, timedelta  # noqa: E402

TITLES = {"TAX INVOICE", "PURCHASE ORDER", "QUOTATION"}
_OCR = [("o", "0"), ("O", "0"), ("l", "1"), ("I", "1"), ("rn", "m"), ("e", "c"), ("S", "5"), ("B", "8")]

OTHER_TEMPLATES = [
    ["DELIVERY NOTE", "Delivery No: DN-{n}", "Date: {d}", "Deliver to: {buyer}, Engineering", "Items delivered:",
     "{qty} x {item}", "Received by: ____________", "Driver: {person}"],
    ["STATEMENT OF ACCOUNT", "Account: {buyer}", "Period: {d} to {d2}", "Opening balance: {amt}",
     "Payments received: {amt2}", "Closing balance: {amt3}", "Please contact accounts@{vend}.example for queries"],
    ["PAYMENT RECEIPT", "Receipt No: RC-{n}", "Received with thanks from {buyer}", "Amount: INR {amt}",
     "Mode: NEFT, UTR {utr}", "Date: {d}"],
    ["{vendor}", "{d}", "Dear {person},", "Thank you for your continued business. Please find our updated product catalogue",
     "and service terms enclosed. Our account manager will contact you next week.", "Regards,", "{person2}"],
    ["CREDIT NOTE", "Credit Note No: CN-{n}", "Against: returned goods", "Customer: {buyer}", "{qty} x {item} returned",
     "Credit amount: INR {amt}", "Date: {d}"],
    ["STATEMENT OF ACCOUNT", "Customer: {buyer}", "Outstanding items:", "Invoice INV-{n} dated {d}: INR {amt}",
     "Invoice INV-{n}1 dated {d2}: INR {amt2}", "Total outstanding: INR {amt3}", "Kindly arrange payment of the invoices above."],
    ["GOODS RECEIPT NOTE", "GRN No: GRN-{n}", "Supplier: {vendor}", "{qty} x {item} received in good condition",
     "Inspected by: {person}", "Date: {d}"],
]
_PEOPLE = ["Priya Sharma", "Rahul Mehta", "Ananya Iyer", "Vikram Rao", "Sneha Kulkarni", "Arjun Nair"]
_BUYERS = ["Acme Corp", "Globex India", "Initech Pvt Ltd", "Umbrella Systems"]


def _garble(text: str, rng: random.Random, rate: float) -> str:
    out = []
    for ch in text:
        r = rng.random()
        if r < rate:
            swaps = [b for a, b in _OCR if a == ch]
            out.append(swaps[0] if swaps else ("" if ch == " " else ch))
        else:
            out.append(ch)
    return "".join(out)


def _other(rng: random.Random, i: int, vendors: list, items: list) -> tuple[str, int]:
    k = rng.randrange(len(OTHER_TEMPLATES))
    t = OTHER_TEMPLATES[k]
    vendor = rng.choice(vendors)["name"]
    fill = dict(n=f"{2026}-{i:05d}", d=f"2026-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
                d2=f"2026-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}", buyer=rng.choice(_BUYERS),
                qty=rng.randint(1, 20), item=rng.choice(items)["name"], person=rng.choice(_PEOPLE),
                person2=rng.choice(_PEOPLE), amt=f"{rng.uniform(1e3, 5e5):,.2f}", amt2=f"{rng.uniform(1e3, 5e5):,.2f}",
                amt3=f"{rng.uniform(1e3, 5e5):,.2f}", utr=rng.randint(10**11, 10**12 - 1), vendor=vendor,
                vend=vendor.split()[0].lower())
    return "\n".join(line.format(**fill) for line in t), k


def corpus(n_per_type: int = 120, n_other: int = 180, seed: int = 29):
    """[(text, label, variant, group)] — three variants of each generated
    document plus `n_other` other documents. `group` is the generator layout
    ("A"/"B"/"C") or the other-template ("other-0"…), for holding a whole
    kind of document out of training."""
    from synthetic_invoice_lib import load_reference_data
    _, vendors, items = load_reference_data()
    rng = random.Random(seed)
    rows = []
    # Layout is drawn independently of the type: the shared generator ties
    # them (invoice=A, po=B, quote=C), which would let a model learn the
    # layout instead of the document type.
    for i in range(n_per_type * 3):
        doc_type = ("invoice", "po", "quote")[i % 3]
        layout = rng.choice("ABC")
        vendor = rng.choice(vendors)
        chosen = []
        for _ in range(rng.randint(1, 3)):
            t = rng.choice(items)
            lo, hi = t["price_range"]
            chosen.append({"name": t["name"], "quantity": rng.randint(1, 8), "unit_price": round(rng.uniform(lo, hi), 2)})
        prefix = {"invoice": "INV", "po": "PO", "quote": "QT"}[doc_type]
        bank = _pick_bank(rng, vendor["name"]) if doc_type in ("invoice", "quote") and rng.random() < 0.6 else None
        lines, _ = render_document(rng, doc_type, layout, vendor, chosen, f"{prefix}-2026-{i:05d}",
                                   date(2026, 1, 15) + timedelta(days=rng.randint(0, 200)), rng.choice(_GEN_BUYERS), bank)
        text = "\n".join(lines)
        rows.append((text, doc_type, "clean", layout))
        rows.append((_garble(text, rng, rng.uniform(0.04, 0.10)), doc_type, "ocr_noise", layout))
        rows.append(("\n".join(l for l in lines if l.strip() not in TITLES), doc_type, "no_title", layout))
    for i in range(n_other):
        text, k = _other(rng, i, vendors, items)
        rows.append((text if rng.random() < 0.7 else _garble(text, rng, 0.06), "other", "other", f"other-{k}"))
    return rows
