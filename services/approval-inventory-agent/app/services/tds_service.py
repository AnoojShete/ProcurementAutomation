"""TDS at booking and MSME payment deadlines (feature expansion Phase 4).

TDS: when an invoice is booked against a purchase request, the tax the
buyer must deduct before paying the vendor is worked out and kept with the
invoice, so the amount actually payable (net_payable) is known:

  section    the vendor's own (vendor tax profile), else the one for the
             request's category (rule tds.category_sections)
  base       the amount before GST (when GST is shown separately), in INR
  threshold  nothing is deducted until one invoice, or the year's total with
             the vendor under that section, passes the section's threshold;
             for purchases of goods (194Q) only the part above it counts
  rate       a valid lower-deduction certificate's rate, else the section's
             rate, or its higher no-PAN rate when the vendor has no PAN
  rounded    to whole rupees

A supplier outside India isn't handled here (non-resident TDS needs a
chartered accountant), and nothing is paid: money moves only at the bank.

MSME: an invoice from a micro or small enterprise must be paid within the
agreed period, at most 45 days (rule msme.payment_days) from acceptance,
or the expense isn't deductible that year (Income-tax Act s. 43B(h)).
Acceptance here is the later of booking the invoice and the last delivery.

All rates and thresholds are seeded with the values current in October 2026
and must be confirmed by the finance team or a chartered accountant.
"""
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text

from shared.money import inr
from shared.rules_engine import get_rule

PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
UDYAM_RE = re.compile(r"^UDYAM-[A-Z]{2}-[0-9]{2}-[0-9]{7}$")
MSME_TRACKED = ("micro", "small")       # s. 43B(h) covers these, not medium enterprises
DEFAULT_SECTIONS = {"hardware": "194Q", "software": "194J(b)", "saas": "194J(a)", "services": "194J(a)"}


@dataclass
class Section:
    section: str
    description: str
    rate_pct: float
    rate_no_pan_pct: float
    threshold_single_inr: Optional[float] = None
    threshold_annual_inr: Optional[float] = None
    above_threshold_only: bool = False
    active: bool = True


@dataclass
class VendorTax:
    pan: Optional[str] = None
    tds_section: Optional[str] = None
    ldc_rate_pct: Optional[float] = None
    ldc_valid_until: Optional[date] = None
    country: Optional[str] = None


@dataclass
class TdsResult:
    section: Optional[str]
    rate_pct: Optional[float]
    base: float
    amount: float
    net_payable: float
    notes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def financial_year(d: date) -> tuple[str, date, date]:
    """Indian financial year, April to March: ('2026-27', 1 Apr 2026, 1 Apr 2027)."""
    start_year = d.year if d.month >= 4 else d.year - 1
    return f"{start_year}-{(start_year + 1) % 100:02d}", date(start_year, 4, 1), date(start_year + 1, 4, 1)


def section_for_category(category: Optional[str]) -> Optional[str]:
    mapping = get_rule("tds.category_sections", fallback=DEFAULT_SECTIONS) or {}
    return mapping.get(category or "") if isinstance(mapping, dict) else None


def compute(section: Optional[Section], vendor: VendorTax, *, total: float, taxable_value: Optional[float],
            year_to_date: float, invoice_date: date, foreign: bool = False) -> TdsResult:
    """year_to_date: the TDS base already booked with this vendor under this
    section in the invoice's financial year, before this invoice."""
    notes: list[str] = []
    base = round(taxable_value if taxable_value is not None else total, 2)

    def none(note: str) -> TdsResult:
        return TdsResult(section.section if section else None, None, base, 0.0, round(total, 2), notes + [note])

    if foreign or (vendor.country and vendor.country.upper() != "IN"):
        return none("Supplier outside India: TDS on payments to non-residents isn't worked out here; ask a "
                    "chartered accountant.")
    if section is None or not section.active:
        return none("No TDS section applies to this purchase.")
    if taxable_value is None:
        notes.append("GST isn't shown separately on the invoice, so TDS is on the full amount.")

    after = year_to_date + base
    if section.above_threshold_only:
        limit = section.threshold_annual_inr or 0
        portion = max(0.0, after - limit) - max(0.0, year_to_date - limit)
        if portion <= 0:
            return none(f"Below the {inr(limit, 0)} yearly threshold for {section.section} "
                        f"({inr(after)} so far this year).")
        if portion < base:
            notes.append(f"Only the {inr(portion)} above the {inr(limit, 0)} yearly threshold is taxed.")
    else:
        single, annual = section.threshold_single_inr, section.threshold_annual_inr
        over = (single is None and annual is None) or (single is not None and base > single) \
            or (annual is not None and after > annual)
        if not over:
            limits = " / ".join(x for x in (single and f"{inr(single, 0)} per invoice",
                                             annual and f"{inr(annual, 0)} a year") if x)
            return none(f"Below the {section.section} threshold ({limits}; {inr(after)} so far this year).")
        portion = base
        if annual is not None and year_to_date <= annual < after and year_to_date > 0:
            notes.append(f"This invoice takes the year's total past {inr(annual, 0)}: TDS on earlier invoices "
                         f"this year ({inr(year_to_date)}) is due as well; check with finance.")

    if vendor.ldc_rate_pct is not None and vendor.ldc_valid_until and invoice_date <= vendor.ldc_valid_until:
        rate = float(vendor.ldc_rate_pct)
        notes.append(f"Lower deduction certificate: {rate:g}% until {vendor.ldc_valid_until.isoformat()}.")
    elif not (vendor.pan and PAN_RE.match(vendor.pan)):
        rate = section.rate_no_pan_pct
        notes.append(f"No PAN on file for the vendor: the higher rate of {rate:g}% applies.")
    else:
        rate = section.rate_pct
    amount = float(round(portion * rate / 100))
    return TdsResult(section.section, rate, base, amount, round(total - amount, 2), notes)


# Tax and MSME dates are Indian calendar dates; the servers run in UTC, so
# between 00:00 and 05:30 IST "today" would otherwise be yesterday.
IST = timezone(timedelta(hours=5, minutes=30))


def today_ist() -> date:
    return datetime.now(IST).date()


def msme_due(acceptance: date, today: date, payment_days: Optional[int] = None,
             warning_days: Optional[int] = None) -> dict:
    payment_days = int(payment_days if payment_days is not None else get_rule("msme.payment_days", fallback=45))
    warning_days = int(warning_days if warning_days is not None else get_rule("msme.warning_days", fallback=7))
    due = acceptance + timedelta(days=payment_days)
    left = (due - today).days
    status = "overdue" if left < 0 else "due_soon" if left <= warning_days else "ok"
    return {"acceptance_date": acceptance.isoformat(), "due_date": due.isoformat(), "days_left": left, "status": status}


# ── database side ────────────────────────────────────────────────────────────

def _section(row) -> Section:
    return Section(row.section, row.description, float(row.rate_pct), float(row.rate_no_pan_pct),
                   float(row.threshold_single_inr) if row.threshold_single_inr is not None else None,
                   float(row.threshold_annual_inr) if row.threshold_annual_inr is not None else None,
                   bool(row.above_threshold_only), bool(row.active))


async def load_section(db, section: Optional[str]) -> Optional[Section]:
    if not section:
        return None
    row = (await db.execute(text("SELECT * FROM tds_sections WHERE section = :s"), {"s": section})).first()
    return _section(row) if row else None


async def tds_for_invoice(db, *, vendor_id: str, document_id: str, request_type: Optional[str], total: float,
                          taxable_value: Optional[float], invoice_date: Optional[date],
                          foreign: bool = False) -> TdsResult:
    from app.services.budget_service import category_for
    v = (await db.execute(text(
        "SELECT pan, tds_section, ldc_rate_pct, ldc_valid_until, country FROM vendors WHERE id = :v"),
        {"v": vendor_id})).first()
    vendor = VendorTax(v.pan, v.tds_section, float(v.ldc_rate_pct) if v.ldc_rate_pct is not None else None,
                       v.ldc_valid_until, v.country) if v else VendorTax()
    section = await load_section(db, vendor.tds_section or section_for_category(category_for(request_type)))
    when = invoice_date or today_ist()
    ytd = 0.0
    if section is not None:
        _, start, end = financial_year(when)
        ytd = float((await db.execute(text(
            "SELECT COALESCE(sum(tds_base), 0) FROM invoice_matches WHERE vendor_id = :v AND tds_section = :s "
            "AND status IN ('matched', 'partial') AND document_id <> :d "
            "AND COALESCE(invoice_date, created_at::date) >= :start AND COALESCE(invoice_date, created_at::date) < :end"),
            {"v": vendor_id, "s": section.section, "d": document_id, "start": start, "end": end})).scalar() or 0)
    return compute(section, vendor, total=total, taxable_value=taxable_value, year_to_date=ytd,
                   invoice_date=when, foreign=foreign)


def parse_date(value) -> Optional[date]:
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)).date() if value else None
    except ValueError:
        return None
