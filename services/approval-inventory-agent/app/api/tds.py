"""TDS and MSME (feature expansion Phase 4): TDS sections, each vendor's
tax profile, the TDS register of booked invoices, MSME payment deadlines,
and recording that an invoice was paid (outside the platform). See
app/services/tds_service.py."""
import uuid
from datetime import date, datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import AuditLog
from app.services import tds_service
from shared.auth import CurrentUser, get_current_user, require_role

router = APIRouter()
READ = Depends(require_role("approver", "finance", "admin"))
EDIT = Depends(require_role("finance", "admin"))


def _f(v) -> Optional[float]:
    return float(v) if v is not None else None


def _audit(db, entity_type: str, entity_id: str, action: str, user: CurrentUser, details: dict):
    db.add(AuditLog(id=str(uuid.uuid4()), entity_type=entity_type, entity_id=entity_id, action=action,
                    performed_by=user.email, details=details, created_at=datetime.now(timezone.utc)))


# ── sections ─────────────────────────────────────────────────────────────────

class SectionBody(BaseModel):
    description: str = Field(min_length=1, max_length=200)
    rate_pct: float = Field(ge=0, le=40)
    rate_no_pan_pct: float = Field(ge=0, le=40)
    threshold_single_inr: Optional[float] = Field(default=None, ge=0)
    threshold_annual_inr: Optional[float] = Field(default=None, ge=0)
    above_threshold_only: bool = False
    active: bool = True


def _section_dict(r) -> dict:
    return {"section": r.section, "description": r.description, "rate_pct": float(r.rate_pct),
            "rate_no_pan_pct": float(r.rate_no_pan_pct), "threshold_single_inr": _f(r.threshold_single_inr),
            "threshold_annual_inr": _f(r.threshold_annual_inr), "above_threshold_only": r.above_threshold_only,
            "active": r.active, "updated_by": r.updated_by,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None}


@router.get("/sections", dependencies=[READ])
async def list_sections(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(text("SELECT * FROM tds_sections ORDER BY section"))).all()
    return {"data": [_section_dict(r) for r in rows],
            "meta": {"category_sections": tds_service.get_rule("tds.category_sections",
                                                               fallback=tds_service.DEFAULT_SECTIONS)}}


@router.put("/sections/{section}", dependencies=[EDIT])
async def save_section(section: str, body: SectionBody, db: AsyncSession = Depends(get_db),
                       user: CurrentUser = Depends(get_current_user)):
    """Adds or changes a section. Applies to invoices booked from now on."""
    if not 2 <= len(section) <= 12:
        raise HTTPException(status_code=422, detail={"code": "invalid_section", "message": "a section code is 2-12 characters"})
    await db.execute(text(
        "INSERT INTO tds_sections (section, description, rate_pct, rate_no_pan_pct, threshold_single_inr, "
        "threshold_annual_inr, above_threshold_only, active, updated_by, updated_at) VALUES (:s, :d, :r, :rn, :ts, "
        ":ta, :above, :active, :u, now()) ON CONFLICT (section) DO UPDATE SET description = EXCLUDED.description, "
        "rate_pct = EXCLUDED.rate_pct, rate_no_pan_pct = EXCLUDED.rate_no_pan_pct, "
        "threshold_single_inr = EXCLUDED.threshold_single_inr, threshold_annual_inr = EXCLUDED.threshold_annual_inr, "
        "above_threshold_only = EXCLUDED.above_threshold_only, active = EXCLUDED.active, "
        "updated_by = EXCLUDED.updated_by, updated_at = now()"),
        {"s": section, "d": body.description, "r": body.rate_pct, "rn": body.rate_no_pan_pct,
         "ts": body.threshold_single_inr, "ta": body.threshold_annual_inr, "above": body.above_threshold_only,
         "active": body.active, "u": user.email})
    # Sections are keyed by code; the audit row gets a stable id per code.
    _audit(db, "tds_section", str(uuid.uuid5(uuid.NAMESPACE_URL, f"tds_section:{section}")), "tds_section_saved",
           user, {"section": section, **body.model_dump()})
    await db.commit()
    row = (await db.execute(text("SELECT * FROM tds_sections WHERE section = :s"), {"s": section})).first()
    return {"data": _section_dict(row)}


# ── vendor tax profile ──────────────────────────────────────────────────────

class VendorTaxBody(BaseModel):
    pan: Optional[str] = None
    tds_section: Optional[str] = None
    ldc_rate_pct: Optional[float] = Field(default=None, ge=0, le=40)
    ldc_valid_until: Optional[date] = None
    msme_udyam_number: Optional[str] = None
    msme_category: Optional[Literal["micro", "small", "medium"]] = None
    annual_turnover_inr: Optional[float] = Field(default=None, ge=0)


def _bad(code: str, message: str):
    raise HTTPException(status_code=422, detail={"code": code, "message": message})


async def _vendor_row(db, vendor_id: uuid.UUID):
    row = (await db.execute(text(
        "SELECT id, name, gstin, country, pan, tds_section, ldc_rate_pct, ldc_valid_until, msme_udyam_number, "
        "msme_category, annual_turnover_inr FROM vendors WHERE id = :v"), {"v": str(vendor_id)})).first()
    if row is None:
        raise HTTPException(status_code=404, detail="vendor not found")
    return row


def _profile(row) -> dict:
    pan_from_gstin = row.gstin[2:12].upper() if row.gstin and len(row.gstin) == 15 else None
    return {"vendor_id": str(row.id), "vendor_name": row.name, "gstin": row.gstin, "country": row.country,
            "pan": row.pan, "pan_from_gstin": pan_from_gstin, "tds_section": row.tds_section,
            "ldc_rate_pct": _f(row.ldc_rate_pct),
            "ldc_valid_until": row.ldc_valid_until.isoformat() if row.ldc_valid_until else None,
            "msme_udyam_number": row.msme_udyam_number, "msme_category": row.msme_category,
            "msme_tracked": row.msme_category in tds_service.MSME_TRACKED,
            "annual_turnover_inr": _f(row.annual_turnover_inr)}


@router.get("/vendors/{vendor_id}", dependencies=[READ])
async def get_vendor_profile(vendor_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    return {"data": _profile(await _vendor_row(db, vendor_id))}


@router.put("/vendors/{vendor_id}", dependencies=[EDIT])
async def save_vendor_profile(vendor_id: uuid.UUID, body: VendorTaxBody, db: AsyncSession = Depends(get_db),
                              user: CurrentUser = Depends(get_current_user)):
    row = await _vendor_row(db, vendor_id)
    pan = (body.pan or "").strip().upper() or None
    if pan and not tds_service.PAN_RE.match(pan):
        _bad("invalid_pan", "a PAN is 5 letters, 4 digits and a letter, e.g. AABCD5678E")
    if pan and row.gstin and len(row.gstin) == 15 and row.gstin[2:12].upper() != pan:
        _bad("pan_gstin_mismatch", f"the vendor's GSTIN {row.gstin} contains PAN {row.gstin[2:12].upper()}, not {pan}")
    section = (body.tds_section or "").strip() or None
    if section and not (await db.execute(text("SELECT 1 FROM tds_sections WHERE section = :s"), {"s": section})).first():
        _bad("unknown_section", f"no TDS section {section}")
    if (body.ldc_rate_pct is None) != (body.ldc_valid_until is None):
        _bad("ldc_incomplete", "a lower deduction certificate needs both its rate and its expiry date")
    udyam = (body.msme_udyam_number or "").strip().upper() or None
    if udyam and not tds_service.UDYAM_RE.match(udyam):
        _bad("invalid_udyam", "an Udyam number looks like UDYAM-KR-03-0012345")
    if bool(udyam) != bool(body.msme_category):
        _bad("msme_incomplete", "an MSME vendor needs both its Udyam number and its category")
    values = {"pan": pan, "tds_section": section, "ldc_rate_pct": body.ldc_rate_pct, "ldc_valid_until": body.ldc_valid_until,
              "msme_udyam_number": udyam, "msme_category": body.msme_category,
              "annual_turnover_inr": body.annual_turnover_inr}
    await db.execute(text(
        "UPDATE vendors SET pan = :pan, tds_section = :tds_section, ldc_rate_pct = :ldc_rate_pct, "
        "ldc_valid_until = :ldc_valid_until, msme_udyam_number = :msme_udyam_number, msme_category = :msme_category, "
        "annual_turnover_inr = :annual_turnover_inr, updated_at = now() WHERE id = :v"), {**values, "v": str(vendor_id)})
    before = _profile(row)
    after = {k: v.isoformat() if isinstance(v, date) else v for k, v in values.items()}
    _audit(db, "vendor", str(vendor_id), "vendor_tax_profile_updated", user,
           {"changed": {k: v for k, v in after.items() if before.get(k) != v}})
    await db.commit()
    return {"data": _profile(await _vendor_row(db, vendor_id))}


# ── TDS register and MSME deadlines ─────────────────────────────────────────

@router.get("/register", dependencies=[READ])
async def register(fy: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    """Booked invoices of a financial year (e.g. 2026-27) with their TDS,
    and totals per quarter and section (what the quarterly TDS return needs)."""
    label, start, end = tds_service.financial_year(tds_service.today_ist())
    if fy:
        try:
            y = int(fy[:4])
            label, start, end = tds_service.financial_year(date(y, 4, 1))
        except ValueError:
            raise HTTPException(status_code=422, detail={"code": "invalid_fy", "message": "fy is like 2026-27"})
    rows = (await db.execute(text(
        "SELECT m.document_id, m.invoice_number, m.vendor_id, v.name AS vendor_name, v.pan, m.purchase_request_id, "
        "m.amount, m.taxable_value, m.gst_amount, m.tds_section, m.tds_rate_pct, m.tds_base, m.tds_amount, "
        "m.net_payable, m.tds_notes, m.paid_at, COALESCE(m.invoice_date, m.created_at::date) AS day "
        "FROM invoice_matches m LEFT JOIN vendors v ON v.id = m.vendor_id "
        "WHERE m.status IN ('matched', 'partial') AND m.tds_section IS NOT NULL "
        "AND COALESCE(m.invoice_date, m.created_at::date) >= :s AND COALESCE(m.invoice_date, m.created_at::date) < :e "
        "ORDER BY day DESC"), {"s": start, "e": end})).all()
    items, totals = [], {}
    for r in rows:
        quarter = f"Q{((r.day.month - 4) % 12) // 3 + 1}"
        key = (quarter, r.tds_section)
        t = totals.setdefault(key, {"quarter": quarter, "section": r.tds_section, "invoices": 0, "base": 0.0, "tds": 0.0})
        t["invoices"] += 1
        t["base"] = round(t["base"] + float(r.tds_base or 0), 2)
        t["tds"] = round(t["tds"] + float(r.tds_amount or 0), 2)
        items.append({"document_id": str(r.document_id), "invoice_number": r.invoice_number,
                      "invoice_date": r.day.isoformat(), "quarter": quarter,
                      "vendor_id": str(r.vendor_id) if r.vendor_id else None, "vendor_name": r.vendor_name, "pan": r.pan,
                      "request_id": str(r.purchase_request_id) if r.purchase_request_id else None,
                      "amount": _f(r.amount), "taxable_value": _f(r.taxable_value), "gst_amount": _f(r.gst_amount),
                      "tds_section": r.tds_section, "tds_rate_pct": _f(r.tds_rate_pct), "tds_base": _f(r.tds_base),
                      "tds_amount": _f(r.tds_amount), "net_payable": _f(r.net_payable), "notes": r.tds_notes or [],
                      "paid_at": r.paid_at.isoformat() if r.paid_at else None})
    return {"data": {"fy": label, "invoices": items,
                     "totals": sorted(totals.values(), key=lambda t: (t["quarter"], t["section"])),
                     "tds_total": round(sum(i["tds_amount"] or 0 for i in items), 2)}}


@router.get("/msme", dependencies=[READ])
async def msme_deadlines(include_paid: bool = False, db: AsyncSession = Depends(get_db)):
    """Booked invoices from micro and small enterprises, with the date they
    must be paid by (rule msme.payment_days after acceptance)."""
    rows = (await db.execute(text(
        "SELECT m.document_id, m.invoice_number, m.vendor_id, v.name AS vendor_name, v.msme_category, "
        "v.msme_udyam_number, m.purchase_request_id, m.amount, m.net_payable, m.paid_at, m.paid_by, "
        "(m.created_at AT TIME ZONE 'Asia/Kolkata')::date AS booked, "
        "(SELECT max(g.received_at AT TIME ZONE 'Asia/Kolkata')::date FROM goods_receipts g "
        "WHERE g.request_id = m.purchase_request_id) AS received "
        "FROM invoice_matches m JOIN vendors v ON v.id = m.vendor_id "
        "WHERE m.status IN ('matched', 'partial') AND v.msme_category IN ('micro', 'small') "
        + ("" if include_paid else "AND m.paid_at IS NULL ") + "ORDER BY m.created_at"))).all()
    today = tds_service.today_ist()
    items = []
    for r in rows:
        due = tds_service.msme_due(max(d for d in (r.booked, r.received) if d), today)
        items.append({"document_id": str(r.document_id), "invoice_number": r.invoice_number,
                      "vendor_id": str(r.vendor_id), "vendor_name": r.vendor_name, "msme_category": r.msme_category,
                      "udyam_number": r.msme_udyam_number,
                      "request_id": str(r.purchase_request_id) if r.purchase_request_id else None,
                      "amount": _f(r.amount), "net_payable": _f(r.net_payable),
                      "paid_at": r.paid_at.isoformat() if r.paid_at else None, "paid_by": r.paid_by,
                      **(due if not r.paid_at else {**due, "status": "paid"})})
    items.sort(key=lambda i: (i["status"] == "paid", i["days_left"]))
    return {"data": items, "meta": {"payment_days": int(tds_service.get_rule("msme.payment_days", fallback=45)),
                                    "warning_days": int(tds_service.get_rule("msme.warning_days", fallback=7))}}


class PaidBody(BaseModel):
    paid_on: Optional[date] = None
    reference: Optional[str] = Field(default=None, max_length=100)


@router.post("/invoices/{document_id}/paid", dependencies=[EDIT])
async def record_paid(document_id: uuid.UUID, body: PaidBody, db: AsyncSession = Depends(get_db),
                      user: CurrentUser = Depends(get_current_user)):
    """Records that an invoice was paid at the bank (nothing is paid from
    here). Who recorded it comes from the token."""
    row = (await db.execute(text(
        "SELECT purchase_request_id, status, paid_at FROM invoice_matches WHERE document_id = :d FOR UPDATE"),
        {"d": str(document_id)})).first()
    if row is None or row.status not in ("matched", "partial"):
        raise HTTPException(status_code=404, detail="no booked invoice with that document id")
    if row.paid_at is not None:
        raise HTTPException(status_code=409, detail={"code": "already_paid", "message": "already recorded as paid"})
    paid_on = body.paid_on or tds_service.today_ist()
    if paid_on > tds_service.today_ist():
        _bad("future_date", "a payment can't be recorded in the future")
    paid_at = datetime(paid_on.year, paid_on.month, paid_on.day, tzinfo=timezone.utc)
    await db.execute(text("UPDATE invoice_matches SET paid_at = :t, paid_by = :u WHERE document_id = :d"),
                     {"t": paid_at, "u": user.email, "d": str(document_id)})
    if row.purchase_request_id:
        _audit(db, "purchase_request", str(row.purchase_request_id), "invoice_paid_recorded", user,
               {"document_id": str(document_id), "paid_on": paid_on.isoformat(), "reference": body.reference})
    await db.commit()
    return {"data": {"document_id": str(document_id), "paid_at": paid_at.isoformat(), "paid_by": user.email}}
