"""GSTR-2B reconciliation (feature expansion Phase 4).

Input tax credit (ITC) can only be claimed for an invoice that appears in
the buyer's GSTR-2B, the monthly statement the GST portal builds from what
suppliers filed. Finance downloads the 2B JSON from the portal and uploads
it here (no paid GSP integration). Each B2B entry is matched to our
invoices on supplier GSTIN + invoice number (fuzzy, with the duplicate
check's threshold) and then compared on taxable value and tax:

    matched          in both, amounts agree
    value_mismatch   in both, taxable value or tax differs
    missing_in_2b    our invoice of that month isn't in the 2B: ITC at
                     risk, chase the supplier to file it
    not_in_books     in the 2B but we have no such invoice: ask for it, or
                     someone may be filing invoices against our GSTIN
"""
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from rapidfuzz import fuzz

from shared.money import inr


class Gstr2bFormatError(ValueError):
    pass


@dataclass
class Entry:
    supplier_gstin: str
    trade_name: Optional[str]
    invoice_number: str
    invoice_date: Optional[str]
    taxable_value: float
    igst: float
    cgst: float
    sgst: float
    total: Optional[float]
    itc_available: Optional[bool]

    @property
    def tax(self) -> float:
        return round(self.igst + self.cgst + self.sgst, 2)


def _f(value) -> float:
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _date(value) -> Optional[str]:
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(value), fmt).date().isoformat()
        except (TypeError, ValueError):
            continue
    return None


def parse(doc: dict) -> tuple[str, Optional[str], list[Entry]]:
    """(period MMYYYY, buyer GSTIN, B2B entries) from the portal's 2B JSON.
    Accepts the file as downloaded ({"data": {...}}) or its "data" part.
    Tax may be at invoice level or summed from the invoice's items."""
    if not isinstance(doc, dict):
        raise Gstr2bFormatError("not a GSTR-2B file: expected a JSON object")
    data = doc.get("data", doc)
    period = str(data.get("rtnprd") or "")
    if not re.fullmatch(r"(0[1-9]|1[0-2])\d{4}", period):
        raise Gstr2bFormatError("not a GSTR-2B file: no return period (rtnprd, MMYYYY)")
    b2b = (data.get("docdata") or {}).get("b2b")
    if not isinstance(b2b, list):
        raise Gstr2bFormatError("not a GSTR-2B file: no docdata.b2b list")
    entries = []
    for supplier in b2b:
        for inv in supplier.get("inv") or []:
            items = inv.get("items") or []
            amounts = {k: _f(inv.get(k)) if k in inv else round(sum(_f(i.get(k)) for i in items), 2)
                       for k in ("txval", "igst", "cgst", "sgst")}
            entries.append(Entry(
                supplier_gstin=str(supplier.get("ctin") or "").upper(), trade_name=supplier.get("trdnm"),
                invoice_number=str(inv.get("inum") or ""), invoice_date=_date(inv.get("dt")),
                taxable_value=amounts["txval"], igst=amounts["igst"], cgst=amounts["cgst"], sgst=amounts["sgst"],
                total=_f(inv.get("val")) if inv.get("val") is not None else None,
                itc_available=None if inv.get("itcavl") is None else str(inv.get("itcavl")).upper() == "Y",
            ))
    return period, (str(data.get("gstin")).upper() if data.get("gstin") else None), entries


def period_bounds(period: str) -> tuple[date, date]:
    month, year = int(period[:2]), int(period[2:])
    start = date(year, month, 1)
    end = date(year + (month == 12), month % 12 + 1, 1)
    return start, end


def _norm(number: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (number or "").upper())


def reconcile(entries: list[Entry], books: list[dict], period: str, *, number_threshold: int = 85,
              tolerance: float = 1.0) -> dict:
    """books: our invoices, each {document_id, supplier_gstin, invoice_number,
    invoice_date (iso or None), taxable_value, gst_total, vendor_name}."""
    start, end = period_bounds(period)
    unused = list(books)
    rows = []
    for e in entries:
        best, best_score = None, 0.0
        for b in unused:
            if (b.get("supplier_gstin") or "").upper() != e.supplier_gstin:
                continue
            score = fuzz.ratio(_norm(e.invoice_number), _norm(b.get("invoice_number") or ""))
            if score >= number_threshold and score > best_score:
                best, best_score = b, score
        if best is None:
            rows.append({"result": "not_in_books", "supplier_gstin": e.supplier_gstin, "supplier": e.trade_name,
                         "invoice_number": e.invoice_number, "invoice_date": e.invoice_date,
                         "taxable_value_2b": e.taxable_value, "tax_2b": e.tax, "document_id": None,
                         "detail": "in the 2B but there is no such invoice in our books"})
            continue
        unused.remove(best)
        diffs = []
        if best.get("taxable_value") is not None and abs(float(best["taxable_value"]) - e.taxable_value) > tolerance:
            diffs.append(f"taxable value {inr(float(best['taxable_value']))} in our books, {inr(e.taxable_value)} in the 2B")
        if best.get("gst_total") is not None and abs(float(best["gst_total"]) - e.tax) > tolerance:
            diffs.append(f"tax {inr(float(best['gst_total']))} in our books, {inr(e.tax)} in the 2B")
        if e.itc_available is False:
            diffs.append("the 2B marks input tax credit as not available")
        rows.append({"result": "value_mismatch" if diffs else "matched", "supplier_gstin": e.supplier_gstin,
                     "supplier": best.get("vendor_name") or e.trade_name, "invoice_number": e.invoice_number,
                     "invoice_date": e.invoice_date, "taxable_value_2b": e.taxable_value, "tax_2b": e.tax,
                     "taxable_value_books": best.get("taxable_value"), "tax_books": best.get("gst_total"),
                     "document_id": best["document_id"], "detail": "; ".join(diffs) or "amounts agree"})
    for b in unused:
        d = b.get("invoice_date")
        if d and start <= date.fromisoformat(d) < end:
            rows.append({"result": "missing_in_2b", "supplier_gstin": b.get("supplier_gstin"),
                         "supplier": b.get("vendor_name"), "invoice_number": b.get("invoice_number"),
                         "invoice_date": d, "taxable_value_books": b.get("taxable_value"), "tax_books": b.get("gst_total"),
                         "document_id": b["document_id"],
                         "detail": "our invoice isn't in the 2B: input tax credit is at risk until the supplier files it"})
    counts = {k: sum(r["result"] == k for r in rows) for k in ("matched", "value_mismatch", "missing_in_2b", "not_in_books")}
    at_risk = sum(float(r.get("tax_books") or 0) for r in rows if r["result"] in ("missing_in_2b", "value_mismatch"))
    return {"summary": {**counts, "entries_in_2b": len(entries), "itc_at_risk_inr": round(at_risk, 2)}, "rows": rows}
