"""Indian GST tax invoices for tests and demos (feature expansion Phase 4):
supplier and buyer GSTIN, place of supply, an HSN/SAC column, CGST + SGST
or IGST, and optionally an e-invoice QR signed like the Invoice
Registration Portal's (a JWT, RS256).

Kept apart from synthetic_invoice_lib.py, whose documents feed the
extraction evaluation and must not change. Used by this service's tests
(tests/test_gst_phase4.py) and by tests/e2e/gst_flow.py.

    lines, total, qr = gst_invoice(SELLER, "29AAACA1234B1ZE", "INV-1", date.today(), ITEMS)
    pdf = build_pdf(lines, qr)
"""
import hashlib
import io
import json
import os
from datetime import date
from typing import Optional

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
# Demo signing key: its public half is shared/einvoice/demo-irp-public-key.pem,
# trusted only when APP_ENV=development (see app/services/einvoice.py).
DEMO_SIGNING_KEY = os.path.join(REPO_ROOT, "data", "einvoice-demo", "demo-irp-signing-key.pem")

STATE_NAMES = {"27": "Maharashtra", "29": "Karnataka", "33": "Tamil Nadu", "07": "Delhi", "36": "Telangana"}


def money(x: float) -> str:
    return f"{x:,.2f}"


def gst_invoice(seller: dict, buyer_gstin: Optional[str], number: str, when: date, items: list, *,
                place_of_supply: Optional[str] = None, split: Optional[str] = None, rate_pct: float = 18.0,
                foreign: bool = False, currency: str = "INR", sign_with: Optional[str] = None,
                qr_overrides: Optional[dict] = None, irn: bool = True) -> tuple[list[str], float, Optional[str]]:
    """seller: {"name", "gstin", "city"}; items: [{"name", "hsn", "quantity", "unit_price"}].
    split: "intra" / "inter" forces CGST+SGST or IGST whatever the states
    (to make a wrong invoice); None picks the right one. sign_with: PEM of a
    private key to sign an e-invoice QR. Returns (lines, total, qr_token)."""
    pos = place_of_supply or (buyer_gstin or "29")[:2]
    lines = [seller["name"], f"{seller.get('city', 'Bengaluru')}, India"]
    if not foreign:
        lines.append(f"GSTIN: {seller['gstin']}")
    lines += ["", "TAX INVOICE" if not foreign else "INVOICE", ""]
    lines.append(f"Invoice Number: {number}")
    lines.append(f"Invoice Date: {when.isoformat()}")
    lines.append("Bill To: Acme Corp IT Department")
    if buyer_gstin and not foreign:
        lines.append(f"Buyer GSTIN: {buyer_gstin}")
        lines.append(f"Place of Supply: {STATE_NAMES.get(pos, pos)} ({pos})")
    irn_value = hashlib.sha256(f"{seller.get('gstin')}{number}{when}".encode()).hexdigest() if sign_with and irn else None
    if irn_value:
        lines.append(f"IRN: {irn_value}")
    lines.append("")
    lines.append(f"{'Description':<34}  {'HSN/SAC':>8}  {'Qty':>4}  {'Unit Price':>12}  {'Line Total':>14}")
    taxable = 0.0
    for it in items:
        line_total = round(it["quantity"] * it["unit_price"], 2)
        taxable += line_total
        code = "" if foreign else it.get("hsn", "")
        lines.append(f"{it['name']:<34}  {code:>8}  {it['quantity']:>4}  {money(it['unit_price']):>12}  {money(line_total):>14}")
    taxable = round(taxable, 2)
    lines.append("")
    if foreign:
        total = taxable
        lines.append(f"Total: {money(total)}")
        lines.append(f"Currency: {currency}")
        return lines, total, None
    lines.append(f"Subtotal: {money(taxable)}")
    lines.append(f"Taxable Value: {money(taxable)}")
    gst = round(taxable * rate_pct / 100, 2)
    intra = (split or ("intra" if seller["gstin"][:2] == pos else "inter")) == "intra"
    if intra:
        half = round(gst / 2, 2)
        lines.append(f"CGST @ {rate_pct / 2:g}%: {money(half)}")
        lines.append(f"SGST @ {rate_pct / 2:g}%: {money(half)}")
        gst = round(half * 2, 2)
    else:
        lines.append(f"IGST @ {rate_pct:g}%: {money(gst)}")
    total = round(taxable + gst, 2)
    lines.append(f"Total Tax: {money(gst)}")
    lines.append(f"Total: {money(total)}")
    lines.append(f"Currency: {currency}")
    token = None
    if sign_with:
        import jwt
        data = {"SellerGstin": seller["gstin"], "BuyerGstin": buyer_gstin, "DocNo": number, "DocTyp": "INV",
                "DocDt": when.strftime("%d/%m/%Y"), "TotInvVal": total, "ItemCnt": len(items),
                "MainHsnCode": items[0].get("hsn"), "Irn": irn_value, "IrnDt": f"{when.isoformat()} 10:00:00"}
        data.update(qr_overrides or {})
        token = jwt.encode({"data": json.dumps(data), "iss": "NIC"}, sign_with, algorithm="RS256")
    return lines, total, token


def demo_signing_key() -> str:
    with open(DEMO_SIGNING_KEY) as f:
        return f.read()


def build_pdf(lines: list[str], qr_token: Optional[str] = None) -> bytes:
    """Text PDF (pdfplumber reads it directly), with the QR at the bottom right."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont("Courier", 9)
    y = 800
    for line in lines:
        c.drawString(40, y, line)
        y -= 13
    if qr_token:
        from reportlab.graphics import renderPDF
        from reportlab.graphics.barcode import qr
        from reportlab.graphics.shapes import Drawing
        widget = qr.QrCodeWidget(qr_token, barLevel="L")
        x0, y0, x1, y1 = widget.getBounds()
        size = 170
        drawing = Drawing(size, size, transform=[size / (x1 - x0), 0, 0, size / (y1 - y0), 0, 0])
        drawing.add(widget)
        renderPDF.draw(drawing, c, 390, 60)
    c.save()
    return buf.getvalue()
