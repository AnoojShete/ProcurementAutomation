"""Reusable generator for synthetic IT-procurement documents (PO / invoice /
quote), as both text-native PDFs (reportlab) and rasterized images (PIL) —
used both to build the checked-in corpus under data/synthetic-invoices/
and, directly, by this service's own pytest suite (so tests don't depend
on the checked-in files being present on disk wherever pytest runs).

Provenance, mirroring data/synthetic-vendors/README.md's pattern:
- If data/reference/it-procurement-reference.csv exists (columns:
  vendor_name, category, item_name, unit_price, currency), vendor names
  and catalog items are seeded from it.
- It almost certainly does not exist yet (no one has built the shared
  reference dataset), so this falls back to a documented, seeded synthetic
  vendor/item catalog (SEED = 42) instead of inventing data ad hoc.
"""
import csv
import io
import os
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont, ImageFilter
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

SEED = 42

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))            # .../document-vendor-agent/scripts
_SERVICE_DIR = os.path.dirname(_THIS_DIR)                          # .../document-vendor-agent
_SERVICES_DIR = os.path.dirname(_SERVICE_DIR)                      # .../services
REPO_ROOT = os.path.dirname(_SERVICES_DIR)                         # repo root

REFERENCE_CSV = os.path.join(REPO_ROOT, "data", "reference", "it-procurement-reference.csv")
DEFAULT_OUTPUT_DIR = os.path.join(REPO_ROOT, "data", "synthetic-invoices")

# --- Documented synthetic fallback (used whenever the reference CSV above
# is absent) ---
_FALLBACK_VENDORS = [
    {"name": "Dell Technologies India Pvt Ltd", "currency": "INR"},
    {"name": "HP India Sales Pvt Ltd", "currency": "INR"},
    {"name": "Lenovo India Pvt Ltd", "currency": "INR"},
    {"name": "Microsoft India Pvt Ltd", "currency": "INR"},
    {"name": "Cisco Systems India Pvt Ltd", "currency": "INR"},
    {"name": "Zoho Corporation", "currency": "INR"},
    {"name": "Wipro Limited", "currency": "INR"},
    {"name": "Freshworks Inc", "currency": "USD"},
    {"name": "Atlassian Pty Ltd", "currency": "USD"},
    {"name": "Amazon Web Services Inc", "currency": "USD"},
]

_FALLBACK_ITEMS = [
    {"name": "Latitude 5540 Laptop", "price_range": (70000, 95000)},
    {"name": "ThinkPad X1 Carbon Laptop", "price_range": (105000, 130000)},
    {"name": "27-inch Monitor", "price_range": (18000, 26000)},
    {"name": "Docking Station", "price_range": (6000, 9000)},
    {"name": "Wireless Keyboard and Mouse Set", "price_range": (1800, 3200)},
    {"name": "Rack Server PowerEdge R650", "price_range": (350000, 480000)},
    {"name": "Enterprise Firewall Appliance", "price_range": (95000, 160000)},
    {"name": "24-Port Network Switch", "price_range": (28000, 45000)},
    {"name": "Microsoft 365 E3 Seat License", "price_range": (1400, 1900)},
    {"name": "Zoho One Seat License", "price_range": (900, 1400)},
    {"name": "Freshdesk Pro Seat License", "price_range": (35, 55)},
    {"name": "Jira Cloud Standard Seat", "price_range": (7, 12)},
    {"name": "AWS Support Plan (Business)", "price_range": (500, 2500)},
    {"name": "Annual Support and Maintenance", "price_range": (15000, 60000)},
]

_BUYERS = [
    "Acme Corp IT Department", "Acme Corp Procurement", "Acme Corp Warehouse",
    "Acme Corp Engineering Team", "Acme Corp Finance Division",
]


def load_reference_data() -> Tuple[bool, List[dict], List[dict]]:
    """Returns (used_reference_csv, vendors, items). See module docstring
    for the CSV schema this looks for."""
    if os.path.exists(REFERENCE_CSV):
        vendors, items, seen = [], [], set()
        with open(REFERENCE_CSV, newline="") as f:
            for row in csv.DictReader(f):
                vname = (row.get("vendor_name") or "").strip()
                if vname and vname not in seen:
                    seen.add(vname)
                    vendors.append({"name": vname, "currency": (row.get("currency") or "INR").strip()})
                iname = (row.get("item_name") or "").strip()
                if iname:
                    try:
                        price = float(row.get("unit_price") or 0)
                    except ValueError:
                        price = 0.0
                    items.append({"name": iname, "price_range": (max(price * 0.9, 1), max(price * 1.1, 2))})
        if vendors and items:
            return True, vendors, items
    return False, list(_FALLBACK_VENDORS), list(_FALLBACK_ITEMS)


def _fmt_money(x: float) -> str:
    return f"{x:,.2f}"


def _slug(text: str) -> str:
    return "".join(c.lower() if c.isalnum() else "" for c in text)[:20] or "vendor"


@dataclass
class GeneratedDoc:
    lines: List[str]
    doc_type: str
    layout: str
    vendor_name: str
    document_number: str
    document_date: date
    total: float
    currency: str
    filename: str = ""
    is_degraded: bool = False
    duplicate_of: Optional[str] = None


def render_document(
    rng: random.Random, doc_type: str, layout: str, vendor: dict, items: List[dict],
    doc_number: str, doc_date: date, buyer: str, bank: Optional[dict] = None,
) -> Tuple[List[str], float]:
    currency = vendor["currency"]
    lines = [vendor["name"], f"{rng.randint(1, 99)} Tech Park, Bengaluru, India", ""]

    title = {"invoice": "TAX INVOICE", "po": "PURCHASE ORDER", "quote": "QUOTATION"}[doc_type]
    lines.append(title)
    lines.append("")

    if doc_type == "invoice":
        number_label = "Invoice Number" if layout in ("A", "C") else "Bill#"
        lines.append(f"{'Invoice No' if layout == 'C' else number_label}: {doc_number}")
        lines.append(f"Invoice Date: {doc_date.isoformat()}")
        lines.append(f"Bill To: {buyer}")
    elif doc_type == "po":
        number_label = "PO Number" if layout in ("A", "C") else "PO#"
        lines.append(f"{'PO No' if layout == 'C' else number_label}: {doc_number}")
        lines.append(f"PO Date: {doc_date.isoformat()}")
        lines.append(f"Ship To: {buyer}")
        lines.append(f"Authorized By: procurement@{_slug(buyer)}.com")
    else:
        number_label = "Quote Number" if layout in ("A", "C") else "QT#"
        lines.append(f"{'Quote No' if layout == 'C' else number_label}: {doc_number}")
        lines.append(f"Quote Date: {doc_date.isoformat()}")
        lines.append(f"Valid Until: {(doc_date + timedelta(days=30)).isoformat()}")

    lines.append("")

    if layout == "B":
        lines.append(f"{'Qty':<5}  {'Item':<40}  {'Unit Price':>12}  {'Line Total':>12}")
    else:
        header_desc = "Item Description" if layout == "C" else "Description"
        lines.append(f"{header_desc:<40}  {'Qty':>5}  {'Unit Price':>12}  {'Line Total':>12}")

    subtotal = 0.0
    for item in items:
        qty = item["quantity"]
        unit_price = item["unit_price"]
        line_total = round(qty * unit_price, 2)
        subtotal += line_total
        if layout == "B":
            lines.append(f"{str(qty):<5}  {item['name']:<40}  {_fmt_money(unit_price):>12}  {_fmt_money(line_total):>12}")
        else:
            lines.append(f"{item['name']:<40}  {str(qty):>5}  {_fmt_money(unit_price):>12}  {_fmt_money(line_total):>12}")

    lines.append("")
    lines.append(f"Subtotal: {_fmt_money(subtotal)}")
    if doc_type == "po":
        total = round(subtotal, 2)
        lines.append(f"Total: {_fmt_money(total)}")
    else:
        tax = round(subtotal * 0.18, 2)
        total = round(subtotal + tax, 2)
        lines.append(f"Tax (18%): {_fmt_money(tax)}")
        total_label = "Amount Due" if (layout == "B" and doc_type == "invoice") else (
            "Grand Total" if (layout == "B" and doc_type == "quote") else "Total"
        )
        lines.append(f"{total_label}: {_fmt_money(total)}")
    lines.append(f"Currency: {currency}")

    if bank:
        lines.append("")
        lines.append("Bank Details (for payment):")
        lines.append(f"Account Name: {bank['beneficiary']}")
        lines.append(f"Bank Account Number: {bank['account_number']}")
        lines.append(f"Routing/IFSC Code: {bank['routing_code']}")

    return lines, total


def build_pdf_bytes(lines: List[str]) -> bytes:
    """Text-native PDF — pdfplumber extracts these directly, no OCR."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont("Courier", 10)
    y = 800
    for line in lines:
        if y < 40:
            c.showPage()
            c.setFont("Courier", 10)
            y = 800
        c.drawString(50, y, line)
        y -= 16
    c.save()
    return buf.getvalue()


def build_image_bytes(rng: random.Random, lines: List[str], degrade: bool = False) -> bytes:
    """Rasterized (scanned-style) document — goes through pytesseract OCR,
    not pdfplumber. `degrade=True` heavily blurs/noises/downsamples the
    render to produce genuinely garbled OCR output, exercising the
    low-confidence review-queue path with real (not simulated) OCR error."""
    font_size = 15
    font = ImageFont.load_default(size=font_size)
    width = 1050
    line_height = font_size + 8
    height = max(320, line_height * (len(lines) + 3))
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    y = 15
    for line in lines:
        draw.text((15, y), line, font=font, fill="black")
        y += line_height

    if degrade:
        noise = Image.effect_noise(img.size, 55).convert("RGB")
        img = Image.blend(img, noise, alpha=0.35)
        img = img.rotate(rng.uniform(-4, 4), expand=True, fillcolor="white")
        img = img.filter(ImageFilter.GaussianBlur(radius=1.8))
        small = img.resize((max(1, img.width // 3), max(1, img.height // 3)))
        img = small.resize((img.width, img.height))

    buf = io.BytesIO()
    if degrade:
        img.save(buf, format="JPEG", quality=10)
    else:
        img.save(buf, format="PNG")
    return buf.getvalue()


def _pick_bank(rng: random.Random, vendor_name: str) -> dict:
    return {
        "beneficiary": vendor_name,
        "account_number": f"{rng.randint(10**10, 10**11 - 1)}",
        "routing_code": f"HDFC0{rng.randint(1000, 9999)}",
    }


def generate_manifest(seed: int = SEED, n_documents: int = 16) -> Tuple[bool, List[GeneratedDoc]]:
    """Pure-Python plan of what to generate (no file I/O) — used both by
    generate_dataset() (writes files) and by tests (renders in-memory)."""
    used_reference, vendors, items = load_reference_data()
    rng = random.Random(seed)

    docs: List[GeneratedDoc] = []
    doc_types = ["invoice", "po", "quote"]
    layouts = ["A", "B", "C"]
    base_date = date(2026, 1, 15)

    counter = 1
    for i in range(n_documents):
        vendor = rng.choice(vendors)
        doc_type = doc_types[i % len(doc_types)]
        layout = layouts[i % len(layouts)]
        buyer = rng.choice(_BUYERS)
        n_items = rng.randint(1, 3)
        chosen_items = []
        for _ in range(n_items):
            template = rng.choice(items)
            lo, hi = template["price_range"]
            chosen_items.append({
                "name": template["name"],
                "quantity": rng.randint(1, 8),
                "unit_price": round(rng.uniform(lo, hi), 2),
            })
        doc_date = base_date + timedelta(days=rng.randint(0, 200))
        prefix = {"invoice": "INV", "po": "PO", "quote": "QT"}[doc_type]
        doc_number = f"{prefix}-2026-{counter:05d}"
        counter += 1

        bank = _pick_bank(rng, vendor["name"]) if doc_type in ("invoice", "quote") and rng.random() < 0.6 else None

        lines, total = render_document(rng, doc_type, layout, vendor, chosen_items, doc_number, doc_date, buyer, bank)
        docs.append(GeneratedDoc(
            lines=lines, doc_type=doc_type, layout=layout, vendor_name=vendor["name"],
            document_number=doc_number, document_date=doc_date, total=total, currency=vendor["currency"],
        ))

    # Intentional near-duplicate invoices: same vendor + amount, date a
    # couple of days apart, a fresh document number — to exercise
    # duplicate-invoice detection.
    for original in [d for d in docs if d.doc_type == "invoice"][:2]:
        dup_number = f"INV-2026-{counter:05d}"
        counter += 1
        dup_lines = list(original.lines)
        dup_lines = [
            line.replace(original.document_number, dup_number) for line in dup_lines
        ]
        dup_date = original.document_date + timedelta(days=2)
        dup_lines = [
            line.replace(original.document_date.isoformat(), dup_date.isoformat()) for line in dup_lines
        ]
        docs.append(GeneratedDoc(
            lines=dup_lines, doc_type="invoice", layout=original.layout, vendor_name=original.vendor_name,
            document_number=dup_number, document_date=dup_date, total=original.total, currency=original.currency,
            duplicate_of=original.filename or "(same generation batch)",
        ))

    # Deliberately low-quality/garbled documents (degraded scanned image)
    # to exercise the review-queue path.
    for i in range(3):
        vendor = rng.choice(vendors)
        template = rng.choice(items)
        lo, hi = template["price_range"]
        item = {"name": template["name"], "quantity": rng.randint(1, 5), "unit_price": round(rng.uniform(lo, hi), 2)}
        doc_date = base_date + timedelta(days=rng.randint(0, 200))
        doc_number = f"INV-2026-{counter:05d}"
        counter += 1
        lines, total = render_document(rng, "invoice", "A", vendor, [item], doc_number, doc_date, rng.choice(_BUYERS))
        docs.append(GeneratedDoc(
            lines=lines, doc_type="invoice", layout="A", vendor_name=vendor["name"],
            document_number=doc_number, document_date=doc_date, total=total, currency=vendor["currency"],
            is_degraded=True,
        ))

    return used_reference, docs


def generate_dataset(output_dir: str = DEFAULT_OUTPUT_DIR, seed: int = SEED, n_documents: int = 16) -> dict:
    os.makedirs(output_dir, exist_ok=True)
    used_reference, docs = generate_manifest(seed=seed, n_documents=n_documents)
    rng = random.Random(seed + 1)

    manifest_entries = []
    for idx, doc in enumerate(docs):
        base = f"{idx:02d}_{doc.doc_type}_{_slug(doc.vendor_name)}_{doc.document_number}"
        if doc.is_degraded:
            filename = base + "_lowquality.jpg"
            data = build_image_bytes(rng, doc.lines, degrade=True)
        elif idx % 5 == 4:
            # a few clean (non-degraded) scanned-style images for OCR variety
            filename = base + ".png"
            data = build_image_bytes(rng, doc.lines, degrade=False)
        else:
            filename = base + ".pdf"
            data = build_pdf_bytes(doc.lines)

        doc.filename = filename
        with open(os.path.join(output_dir, filename), "wb") as f:
            f.write(data)

        manifest_entries.append({
            "filename": filename,
            "doc_type": doc.doc_type,
            "layout": doc.layout,
            "vendor_name": doc.vendor_name,
            "document_number": doc.document_number,
            "document_date": doc.document_date.isoformat(),
            "total": doc.total,
            "currency": doc.currency,
            "is_degraded": doc.is_degraded,
            "duplicate_of": doc.duplicate_of,
        })

    import json
    with open(os.path.join(output_dir, "manifest.json"), "w") as f:
        json.dump({"seed": seed, "used_reference_csv": used_reference, "documents": manifest_entries}, f, indent=2)

    return {"used_reference_csv": used_reference, "count": len(docs), "output_dir": output_dir}


if __name__ == "__main__":
    result = generate_dataset()
    print(f"Generated {result['count']} documents in {result['output_dir']} "
          f"(Kaggle/reference CSV used: {result['used_reference_csv']})")
