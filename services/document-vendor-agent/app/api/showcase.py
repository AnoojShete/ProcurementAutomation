"""Showcase-only scenario: an invoice from a lookalike vendor.

Picks a real vendor, derives a name that's close but not close enough to
match it ("Dell Technologies" -> "De1l Technologies"), renders an invoice
carrying new bank details, and uploads it through the normal path (ClamAV
scan, MinIO, outbox, worker pipeline). The pipeline's own controls do the
rest: the bank details go to the verification queue instead of onto the
vendor, the lookalike is flagged, and the invoice is put on payment hold.

Disabled unless APP_SHOWCASE_MODE is on (the default for demo stacks).
"""
import io
import random
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from rapidfuzz import fuzz
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import Vendor
from app.services.upload_service import scan_upload, store_and_record_upload
from app.services.vendor_matching import normalize_vendor_name
from shared.auth import CurrentUser, get_current_user, require_role

router = APIRouter(dependencies=[Depends(require_role("finance", "admin"))])

_SWAPS = [("l", "1"), ("o", "0"), ("i", "l"), ("e", "3"), ("a", "@"), ("s", "5"), ("n", "m")]


def lookalike_name(name: str, low: float = 70, high: float = 88) -> str | None:
    """A variant of `name` whose match score against it falls in [low, high)
    — similar enough to fool a reader, not similar enough to match."""
    base = normalize_vendor_name(name)
    words = name.split()
    for n_swaps in (1, 2, 3):
        variant = name
        done = 0
        for old, new in _SWAPS:
            if old in variant.lower() and done < n_swaps:
                i = variant.lower().index(old)
                variant = variant[:i] + new + variant[i + 1:]
                done += 1
        score = fuzz.token_sort_ratio(base, normalize_vendor_name(variant))
        if low <= score < high:
            return variant
    if len(words) > 1:
        variant = " ".join(words[:-1] + ["Services"])
        if low <= fuzz.token_sort_ratio(base, normalize_vendor_name(variant)) < high:
            return variant
    return None


def _invoice_pdf(vendor_name: str, number: str, lines: list[tuple[str, int, float]], bank: dict | None,
                 total_label: str = "Total", tax_label: str = "Tax (18%)") -> bytes:
    subtotal = sum(q * p for _, q, p in lines)
    tax = round(subtotal * 0.18, 2)
    text_lines = [
        vendor_name, "17 Tech Park, Bengaluru, India", "", "TAX INVOICE", "",
        f"Invoice Number: {number}", f"Invoice Date: {date.today().isoformat()}", "Bill To: Acme Corp IT Department", "",
        f"{'Description':<40}  {'Qty':>5}  {'Unit Price':>12}  {'Line Total':>12}",
    ]
    for desc, qty, price in lines:
        text_lines.append(f"{desc:<40}  {qty:>5}  {price:>12,.2f}  {qty * price:>12,.2f}")
    text_lines += [
        "", f"Subtotal: {subtotal:,.2f}", f"{tax_label}: {tax:,.2f}", f"{total_label}: {subtotal + tax:,.2f}", "Currency: INR",
    ]
    if bank:
        text_lines += [
            "", "Bank Details (for payment):", f"Account Name: {bank['beneficiary']}",
            f"Bank Account Number: {bank['account_number']}", f"Routing/IFSC Code: {bank['routing_code']}",
        ]
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont("Courier", 10)
    y = 800
    for line in text_lines:
        c.drawString(50, y, line)
        y -= 16
    c.save()
    return buf.getvalue()


@router.post("/lookalike-invoice")
async def lookalike_invoice(request: Request, db: AsyncSession = Depends(get_db),
                            user: CurrentUser = Depends(get_current_user)):
    if not settings.showcase_mode:
        raise HTTPException(status_code=404, detail="showcase mode is off")
    vendors = (await db.execute(select(Vendor).where(Vendor.status == "active"))).scalars().all()
    rng = random.Random()
    rng.shuffle(vendors)
    target, fake = None, None
    for v in vendors:
        if len(v.name or "") < 8 or v.name.lower().startswith(("unknown", "unspecified")):
            continue
        fake = lookalike_name(v.name)
        if fake:
            target = v
            break
    if target is None:
        raise HTTPException(status_code=409, detail="no vendor with a name suitable for a lookalike yet — process a few documents first")

    number = f"INV-SC-{rng.randint(10000, 99999)}"
    bank = {
        "beneficiary": fake,
        "account_number": str(rng.randint(10**11, 10**12 - 1)),
        "routing_code": f"HDFC0{rng.randint(100000, 999999)}",
    }
    pdf = _invoice_pdf(fake, number, [("Dell Latitude 5440 Laptop", 2, 78500.0), ("USB-C Dock", 2, 8900.0)], bank)
    filename = f"showcase_lookalike_{number}.pdf"
    await scan_upload(pdf, db, filename)
    doc = await store_and_record_upload(
        db, request.app.state.kafka_producer, pdf, filename, "application/pdf", user.email,
    )
    return {"data": {
        "document_id": doc.id, "impersonated_vendor": target.name, "impersonated_vendor_id": target.id,
        "lookalike_name": fake, "invoice_number": number, "bank_account_last4": bank["account_number"][-4:],
    }}


LEARNING_VENDOR = "Northwind Office Supplies Pvt Ltd"


@router.post("/unusual-label-invoice")
async def unusual_label_invoice(request: Request, db: AsyncSession = Depends(get_db),
                                user: CurrentUser = Depends(get_current_user)):
    """An invoice from a vendor that labels its total "Balance Payable" —
    which the extractor doesn't recognise, so the total comes out empty.
    Correct the total on two of these and the third is read correctly:
    the learning stage has picked up the vendor's label."""
    if not settings.showcase_mode:
        raise HTTPException(status_code=404, detail="showcase mode is off")
    rng = random.Random()
    number = f"NW-{rng.randint(1000, 9999)}"
    qty = rng.randint(2, 9)
    lines = [("Ergonomic Office Chair", qty, 12500.0), ("Desk Lamp", rng.randint(2, 6), 1850.0)]
    total = round(sum(q * p for _, q, p in lines) * 1.18, 2)
    pdf = _invoice_pdf(LEARNING_VENDOR, number, lines, None, total_label="Balance Payable", tax_label="GST @18%")
    filename = f"showcase_northwind_{number}.pdf"
    await scan_upload(pdf, db, filename)
    doc = await store_and_record_upload(
        db, request.app.state.kafka_producer, pdf, filename, "application/pdf", user.email,
    )
    return {"data": {"document_id": doc.id, "vendor": LEARNING_VENDOR, "invoice_number": number, "total": total}}
