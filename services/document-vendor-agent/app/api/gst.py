"""GST (feature expansion Phase 4): the tax check of each invoice, the GST
rate table, a monthly summary, and GSTR-2B reconciliation. Finance and
admin; approvers may read."""
import json
import uuid
from datetime import date, datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services import gstr2b
from app.services.audit import write_audit_log
from shared.auth import CurrentUser, get_current_user, require_role
from shared.rules_engine import get_rule

router = APIRouter()
READ = Depends(require_role("approver", "finance", "admin"))
EDIT = Depends(require_role("finance", "admin"))
MAX_2B_BYTES = 10 * 1024 * 1024


def _month(month: Optional[str]) -> tuple[date, date, str]:
    """'2026-10' -> [1 Oct, 1 Nov), and the 2B period '102026'."""
    if month is None:
        today = date.today()
        month = f"{today.year}-{today.month:02d}"
    try:
        year, mon = (int(x) for x in month.split("-"))
        start = date(year, mon, 1)
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail={"code": "invalid_month", "message": "month is YYYY-MM"})
    return start, date(year + (mon == 12), mon % 12 + 1, 1), f"{mon:02d}{year}"


# ── rates ────────────────────────────────────────────────────────────────────

class RateBody(BaseModel):
    code: str = Field(pattern=r"^[0-9]{4,8}$")
    description: str = Field(min_length=1, max_length=200)
    category: Literal["hardware", "software", "saas", "services"]
    rate_pct: float = Field(ge=0, le=40)


@router.get("/rates", dependencies=[READ])
async def list_rates(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(text(
        "SELECT code, description, category, rate_pct, updated_by, updated_at FROM gst_rates ORDER BY code"))).all()
    return {"data": [{"code": r.code, "description": r.description, "category": r.category,
                      "rate_pct": float(r.rate_pct), "updated_by": r.updated_by,
                      "updated_at": r.updated_at.isoformat() if r.updated_at else None} for r in rows]}


@router.put("/rates/{code}", dependencies=[EDIT])
async def save_rate(code: str, body: RateBody, db: AsyncSession = Depends(get_db),
                    user: CurrentUser = Depends(get_current_user)):
    """Adds or changes the rate for one HSN/SAC code (or prefix). Applies to
    invoices read from now on; earlier tax checks keep the rate they used."""
    if body.code != code:
        raise HTTPException(status_code=422, detail={"code": "code_mismatch", "message": "code in the path and body differ"})
    old = (await db.execute(text("SELECT rate_pct FROM gst_rates WHERE code = :c"), {"c": code})).scalar()
    await db.execute(text(
        "INSERT INTO gst_rates (code, description, category, rate_pct, updated_by, updated_at) "
        "VALUES (:c, :d, :cat, :r, :u, now()) ON CONFLICT (code) DO UPDATE SET description = EXCLUDED.description, "
        "category = EXCLUDED.category, rate_pct = EXCLUDED.rate_pct, updated_by = EXCLUDED.updated_by, updated_at = now()"),
        {"c": code, "d": body.description, "cat": body.category, "r": body.rate_pct, "u": user.email})
    # Rate rows are keyed by code, not a uuid: the code is in the payload.
    await write_audit_log(db, entity_type="gst_rate", entity_id=None, action="gst_rate_saved",
                          payload={"code": code, "old_rate_pct": float(old) if old is not None else None,
                                   "rate_pct": body.rate_pct, "by": user.email})
    await db.commit()
    return {"data": {"code": code, **body.model_dump()}}


# ── invoices and the monthly summary ────────────────────────────────────────

def _invoice_row(r) -> dict:
    t = r.tax_check or {}
    return {"document_id": str(r.id), "invoice_number": r.document_number, "invoice_date": r.document_date.isoformat() if r.document_date else None,
            "vendor_id": str(r.vendor_id) if r.vendor_id else None, "vendor_name": r.vendor_name or r.vendor_name_raw,
            "currency": r.currency, "total": float(r.total) if r.total is not None else None,
            "total_inr": float(r.total_inr) if r.total_inr is not None else None,
            "status": t.get("status"), "supply_type": t.get("supply_type"), "supplier_gstin": t.get("supplier_gstin"),
            "taxable_value": t.get("taxable_value"), "cgst": t.get("cgst"), "sgst": t.get("sgst"), "igst": t.get("igst"),
            "gst_total": t.get("gst_total"), "reverse_charge": bool(t.get("reverse_charge")),
            "gst_payable_inr": t.get("gst_payable_inr"), "itc_eligible": bool(t.get("itc_eligible")),
            "einvoice_verified": (t.get("einvoice") or {}).get("verified"), "issues": t.get("issues") or []}


async def _invoices(db: AsyncSession, start: date, end: date, status: Optional[str] = None) -> list[dict]:
    rows = (await db.execute(text(
        "SELECT d.id, d.document_number, d.document_date, d.vendor_id, v.name AS vendor_name, d.vendor_name_raw, "
        "d.currency, d.total, d.total_inr, d.tax_check FROM documents d LEFT JOIN vendors v ON v.id = d.vendor_id "
        "WHERE d.document_type = 'invoice' AND d.tax_check IS NOT NULL "
        "AND COALESCE(d.document_date, d.uploaded_at::date) >= :s AND COALESCE(d.document_date, d.uploaded_at::date) < :e "
        + ("AND d.tax_check->>'status' = :status " if status else "")
        + "ORDER BY COALESCE(d.document_date, d.uploaded_at::date) DESC, d.uploaded_at DESC"),
        {"s": start, "e": end, **({"status": status} if status else {})})).all()
    return [_invoice_row(r) for r in rows]


@router.get("/invoices", dependencies=[READ])
async def list_invoices(month: Optional[str] = None, status: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    start, end, _ = _month(month)
    return {"data": await _invoices(db, start, end, status)}


@router.get("/summary", dependencies=[READ])
async def summary(month: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    """Input tax of the month's invoices that passed the check, GST payable
    under reverse charge, and how many invoices need attention."""
    start, end, period = _month(month)
    invoices = await _invoices(db, start, end)
    ok = [i for i in invoices if i["status"] == "ok"]
    last = (await db.execute(text(
        "SELECT id, uploaded_at, summary FROM gstr2b_uploads WHERE period = :p ORDER BY uploaded_at DESC LIMIT 1"),
        {"p": period})).first()
    return {"data": {
        "month": start.isoformat()[:7], "period": period, "invoices": len(invoices),
        "by_status": {s: sum(i["status"] == s for i in invoices)
                      for s in ("ok", "flagged", "incomplete", "reverse_charge", "import_goods")},
        "input_tax": {k: round(sum(i[k] or 0 for i in ok), 2) for k in ("cgst", "sgst", "igst")},
        "itc_eligible_inr": round(sum(i["gst_total"] or 0 for i in ok if i["itc_eligible"]), 2),
        "reverse_charge_payable_inr": round(sum(i["gst_payable_inr"] or 0 for i in invoices if i["reverse_charge"]), 2),
        "buyer_gstin": get_rule("gst.buyer_gstin", fallback="") or None,
        "last_2b": {"id": str(last.id), "uploaded_at": last.uploaded_at.isoformat(), **(last.summary or {})} if last else None,
    }}


# ── GSTR-2B ──────────────────────────────────────────────────────────────────

async def _books(db: AsyncSession) -> list[dict]:
    rows = (await db.execute(text(
        "SELECT d.id, d.document_number, d.document_date, d.tax_check, COALESCE(v.name, d.vendor_name_raw) AS vendor_name "
        "FROM documents d LEFT JOIN vendors v ON v.id = d.vendor_id WHERE d.document_type = 'invoice' "
        "AND d.status = 'classified' AND d.tax_check->>'supplier_gstin' IS NOT NULL"))).all()
    return [{"document_id": str(r.id), "supplier_gstin": r.tax_check.get("supplier_gstin"), "invoice_number": r.document_number,
             "invoice_date": r.document_date.isoformat() if r.document_date else None, "vendor_name": r.vendor_name,
             "taxable_value": r.tax_check.get("taxable_value"), "gst_total": r.tax_check.get("gst_total")} for r in rows]


@router.post("/2b", dependencies=[EDIT], status_code=201)
async def upload_2b(file: UploadFile = File(...), db: AsyncSession = Depends(get_db),
                    user: CurrentUser = Depends(get_current_user)):
    """Reconciles a GSTR-2B JSON file (as downloaded from the GST portal)
    with our invoices and keeps the result."""
    raw = await file.read(MAX_2B_BYTES + 1)
    if len(raw) > MAX_2B_BYTES:
        raise HTTPException(status_code=413, detail={"code": "file_too_large", "message": "a 2B file is at most 10 MB"})
    try:
        period, buyer, entries = gstr2b.parse(json.loads(raw))
    except (ValueError, UnicodeDecodeError) as e:
        raise HTTPException(status_code=422, detail={"code": "invalid_2b", "message": str(e) if isinstance(e, gstr2b.Gstr2bFormatError) else "not a JSON file"})
    ours = (get_rule("gst.buyer_gstin", fallback="") or "").upper()
    if buyer and ours and buyer != ours:
        raise HTTPException(status_code=422, detail={"code": "wrong_gstin",
                                                     "message": f"this 2B is for {buyer}, our GSTIN is {ours}"})
    result = gstr2b.reconcile(
        entries, await _books(db), period,
        number_threshold=int(get_rule("vendor.duplicate_invoice_number_fuzzy_threshold", fallback=85)),
        tolerance=float(get_rule("gst.tax_tolerance_inr", fallback=1.0)))
    upload_id = str(uuid.uuid4())
    await db.execute(text(
        "INSERT INTO gstr2b_uploads (id, period, buyer_gstin, filename, uploaded_by, uploaded_at, summary, results) "
        "VALUES (:id, :p, :b, :f, :u, :t, CAST(:s AS jsonb), CAST(:r AS jsonb))"),
        {"id": upload_id, "p": period, "b": buyer, "f": file.filename, "u": user.email, "t": datetime.now(timezone.utc),
         "s": json.dumps(result["summary"]), "r": json.dumps(result["rows"])})
    await write_audit_log(db, entity_type="gstr2b", entity_id=upload_id, action="gstr2b_reconciled",
                          payload={"period": period, **result["summary"], "by": user.email})
    await db.commit()
    return {"data": {"id": upload_id, "period": period, "buyer_gstin": buyer, **result}}


@router.get("/2b", dependencies=[READ])
async def list_2b(limit: int = Query(24, ge=1, le=200), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(text(
        "SELECT id, period, buyer_gstin, filename, uploaded_by, uploaded_at, summary FROM gstr2b_uploads "
        "ORDER BY uploaded_at DESC LIMIT :n"), {"n": limit})).all()
    return {"data": [{"id": str(r.id), "period": r.period, "buyer_gstin": r.buyer_gstin, "filename": r.filename,
                      "uploaded_by": r.uploaded_by, "uploaded_at": r.uploaded_at.isoformat(), "summary": r.summary}
                     for r in rows]}


@router.get("/2b/{upload_id}", dependencies=[READ])
async def get_2b(upload_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    r = (await db.execute(text(
        "SELECT id, period, buyer_gstin, filename, uploaded_by, uploaded_at, summary, results FROM gstr2b_uploads "
        "WHERE id = :id"), {"id": str(upload_id)})).first()
    if r is None:
        raise HTTPException(status_code=404, detail="2B upload not found")
    return {"data": {"id": str(r.id), "period": r.period, "buyer_gstin": r.buyer_gstin, "filename": r.filename,
                     "uploaded_by": r.uploaded_by, "uploaded_at": r.uploaded_at.isoformat(),
                     "summary": r.summary, "rows": r.results}}
