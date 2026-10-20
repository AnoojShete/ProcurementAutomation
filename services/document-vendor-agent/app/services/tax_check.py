"""GST check of an invoice (feature expansion Phase 4). Pure: everything it
needs is passed in, so each rule is easy to test and explain.

    domestic invoice   supplier GSTIN valid and the vendor's own; addressed
                       to our GSTIN (gst.buyer_gstin); CGST + SGST when the
                       supplier and the place of supply are in the same
                       state, IGST otherwise; the rate expected for its
                       HSN/SAC codes (gst_rates); taxable value + GST =
                       total; the signed e-invoice QR matches the invoice
    foreign supplier   no GSTIN and not in India: services are under
                       reverse charge, so the buyer pays the GST; goods pay
                       IGST at customs instead

Statuses: ok, flagged (something is wrong: forces review), incomplete (no
GST breakdown printed, so nothing could be checked; flagged instead when
gst.require_breakdown is on), reverse_charge, import_goods.

All rates and the e-invoice threshold are business rules or table rows
seeded with the values current in October 2026; the finance team or a
chartered accountant must confirm them before use.
"""
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from app.services.einvoice import EinvoiceResult
from app.services.gstin_service import validate_gstin_offline
from app.services.tax_extraction import STATES, TaxFields
from shared.money import inr
from shared.taxonomy.line_item_categories import categorize_line_item

DEFAULT_RATE = 18.0


@dataclass
class TaxContext:
    currency: str = "INR"
    total: Optional[float] = None            # printed total
    total_inr: Optional[float] = None
    invoice_number: Optional[str] = None
    line_items: list = field(default_factory=list)
    vendor_gstin: Optional[str] = None       # vendor master
    vendor_country: Optional[str] = None
    vendor_turnover_inr: Optional[float] = None
    buyer_gstin: Optional[str] = None        # rule gst.buyer_gstin
    tolerance: float = 1.0                   # rule gst.tax_tolerance_inr
    require_breakdown: bool = False          # rule gst.require_breakdown
    einvoice_turnover_inr: float = 50_000_000  # rule gst.einvoice_required_turnover_inr
    rates: dict = field(default_factory=dict)  # HSN/SAC code or prefix -> {"rate_pct", "category", "description"}


def rate_for(code: str, rates: dict) -> Optional[dict]:
    """Longest matching prefix: 84713010 uses the row for 8471."""
    for n in range(len(code), 3, -1):
        if code[:n] in rates:
            return rates[code[:n]]
    return None


def _category_rate(categories: list[str], rates: dict) -> float:
    """The usual rate for the invoice's item categories (most common rate
    among the table rows of that category)."""
    wanted = set(categories) | ({"saas", "software"} if "software" in categories else set())
    found = Counter(float(r["rate_pct"]) for r in rates.values() if r.get("category") in wanted)
    return found.most_common(1)[0][0] if found else DEFAULT_RATE


def _money(x: Optional[float]) -> str:
    return inr(x)


def check(tax: TaxFields, ctx: TaxContext, einvoice: Optional[EinvoiceResult] = None) -> dict:
    checks: list[dict] = []
    notes: list[str] = []

    def add(name: str, ok: bool, detail: str):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    out = {**tax.to_dict(), "supply_type": "unknown", "expected_rate_pct": None, "effective_rate_pct": None,
           "reverse_charge": False, "gst_payable_inr": None, "itc_eligible": False,
           "einvoice": einvoice.to_dict() if einvoice else {"present": False}}
    currency = (ctx.currency or "INR").upper()
    categories = [categorize_line_item(li.get("description") or "") for li in ctx.line_items or []] or ["services"]
    foreign = not tax.supplier_gstin and (currency != "INR" or (ctx.vendor_country or "IN").upper() != "IN")

    # ── foreign supplier ────────────────────────────────────────────────────
    if foreign:
        out["supply_type"] = "import"
        if tax.has_breakdown:
            add("no GST charged by a foreign supplier", False,
                f"a supplier without a GSTIN charged GST of {_money(tax.gst_total)}")
        if all(c == "hardware" for c in categories):
            notes.append("Imported goods: IGST is paid to customs when the goods arrive, not on this invoice.")
            return _finish(out, checks, notes, "import_goods")
        rate = _category_rate(categories, ctx.rates)
        base = ctx.total_inr if ctx.total_inr is not None else ctx.total
        out.update(reverse_charge=True, expected_rate_pct=rate,
                   gst_payable_inr=round(base * rate / 100, 2) if base is not None else None)
        notes.append(f"Import of services from a supplier outside India: we pay IGST at {rate:g}% under reverse "
                     f"charge ({_money(out['gst_payable_inr'])}) and can claim it back as input tax credit.")
        return _finish(out, checks, notes, "reverse_charge")

    # ── domestic ────────────────────────────────────────────────────────────
    if not tax.has_breakdown and not tax.reverse_charge_marked:
        if ctx.require_breakdown:
            add("GST breakdown printed", False, "no CGST, SGST or IGST amounts found on the invoice")
            return _finish(out, checks, notes, "flagged")
        notes.append("No CGST, SGST or IGST amounts found on the invoice, so GST wasn't checked.")
        return _finish(out, checks, notes, "incomplete")

    if tax.supplier_gstin:
        valid, reason = validate_gstin_offline(tax.supplier_gstin)
        add("supplier GSTIN valid", valid, reason or f"{tax.supplier_gstin} passes the format and check-digit tests")
        if ctx.vendor_gstin:
            add("supplier GSTIN is the vendor's", ctx.vendor_gstin.upper() == tax.supplier_gstin.upper(),
                f"invoice shows {tax.supplier_gstin}, the vendor master has {ctx.vendor_gstin}")
    else:
        add("supplier GSTIN printed", False, "an Indian tax invoice must show the supplier's GSTIN")

    if tax.buyer_gstin:
        if ctx.buyer_gstin:
            add("addressed to our GSTIN", tax.buyer_gstin.upper() == ctx.buyer_gstin.upper(),
                f"invoice is addressed to {tax.buyer_gstin}, ours is {ctx.buyer_gstin}: input tax credit can't be "
                f"claimed on it" if tax.buyer_gstin.upper() != ctx.buyer_gstin.upper() else f"addressed to {tax.buyer_gstin}")
    else:
        add("our GSTIN printed", False, "the invoice doesn't show our GSTIN, which input tax credit needs")

    if tax.reverse_charge_marked:
        rate = _category_rate(categories, ctx.rates)
        base = tax.taxable_value if tax.taxable_value is not None else ctx.total
        out.update(reverse_charge=True, expected_rate_pct=rate,
                   gst_payable_inr=round(base * rate / 100, 2) if base is not None else None)
        notes.append(f"Marked reverse charge: we pay the GST ({_money(out['gst_payable_inr'])}), not the supplier.")
        return _finish(out, checks, notes, "flagged" if any(not c["ok"] for c in checks) else "reverse_charge")

    # Same state -> CGST + SGST; different states -> IGST.
    supplier_state = (tax.supplier_gstin or "")[:2] or None
    pos = tax.place_of_supply or (tax.buyer_gstin or ctx.buyer_gstin or "")[:2] or None
    if supplier_state and pos:
        intra = supplier_state == pos
        out["supply_type"] = "intra_state" if intra else "inter_state"
        where = (f"supplier in {STATES.get(supplier_state, supplier_state)}, place of supply "
                 f"{STATES.get(pos, pos)}")
        if intra:
            add("CGST + SGST for a supply within the state", bool(tax.cgst and tax.sgst and not tax.igst),
                f"{where}: expected CGST + SGST" + (f", found IGST {_money(tax.igst)}" if tax.igst else ""))
            if tax.cgst is not None and tax.sgst is not None:
                add("CGST equals SGST", abs(tax.cgst - tax.sgst) <= ctx.tolerance,
                    f"CGST {_money(tax.cgst)}, SGST {_money(tax.sgst)}")
        else:
            add("IGST for a supply between states", bool(tax.igst and not tax.cgst and not tax.sgst),
                f"{where}: expected IGST" + (f", found CGST/SGST {_money((tax.cgst or 0) + (tax.sgst or 0))}"
                                            if (tax.cgst or tax.sgst) else ""))

    # Rate from the HSN/SAC codes.
    gst = tax.gst_total or 0.0
    if tax.hsn_codes:
        known = [(c, rate_for(c["code"], ctx.rates)) for c in tax.hsn_codes]
        unknown = sorted({c["code"] for c, r in known if r is None})
        if unknown:
            notes.append(f"HSN/SAC {', '.join(unknown)} not in the GST rate table; its rate wasn't checked.")
        rated = [(c, r) for c, r in known if r is not None]
        if rated and tax.taxable_value:
            if all(c.get("line_total") is not None for c, _ in rated) and len(rated) == len(known):
                expected_gst = sum(c["line_total"] * float(r["rate_pct"]) / 100 for c, r in rated)
            else:
                expected_gst = tax.taxable_value * float(rated[0][1]["rate_pct"]) / 100
            expected_rate = round(expected_gst / tax.taxable_value * 100, 2)
            out["expected_rate_pct"] = expected_rate
            out["effective_rate_pct"] = round(gst / tax.taxable_value * 100, 2)
            add("GST rate matches the HSN/SAC codes", abs(gst - expected_gst) <= max(ctx.tolerance, 0.005 * expected_gst),
                f"expected {expected_rate:g}% ({_money(round(expected_gst, 2))}) for "
                f"{', '.join(sorted({c['code'] for c, _ in rated}))}; charged {out['effective_rate_pct']:g}% ({_money(gst)})")
    else:
        notes.append("No HSN/SAC codes found, so the GST rate wasn't checked.")

    if tax.taxable_value is not None and ctx.total is not None:
        expected_total = tax.taxable_value + gst + (tax.cess or 0)
        add("taxable value + GST = total", abs(expected_total - ctx.total) <= ctx.tolerance,
            f"{_money(tax.taxable_value)} + {_money(gst)} = {_money(round(expected_total, 2))}; invoice total "
            f"{_money(ctx.total)}")

    # E-invoice QR.
    if einvoice and einvoice.present:
        if einvoice.verified is False:
            add("e-invoice QR signed by the IRP", False, einvoice.error or "signature check failed")
        elif einvoice.verified:
            add("e-invoice QR signed by the IRP", True, "signature valid")
            add("e-invoice QR matches the invoice", not einvoice.mismatches,
                "; ".join(einvoice.mismatches) or "seller, buyer, number and total agree")
        else:
            notes.append(f"E-invoice QR found but not verified: {einvoice.error}")
    elif ctx.vendor_turnover_inr is not None and ctx.vendor_turnover_inr > ctx.einvoice_turnover_inr:
        add("e-invoice QR present", False,
            f"the supplier's turnover ({_money(ctx.vendor_turnover_inr)}) is above {_money(ctx.einvoice_turnover_inr)}, "
            f"so its invoices must be e-invoices with a signed QR")
    elif tax.irn:
        notes.append("An IRN is printed but no readable QR code was found.")

    status = "flagged" if any(not c["ok"] for c in checks) else "ok"
    out["itc_eligible"] = status == "ok" and bool(tax.buyer_gstin)
    return _finish(out, checks, notes, status)


def _finish(out: dict, checks: list, notes: list, status: str) -> dict:
    out.update(status=status, checks=checks, notes=notes, issues=[c["detail"] for c in checks if not c["ok"]])
    return out
