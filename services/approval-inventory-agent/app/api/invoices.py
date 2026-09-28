"""Invoice ledger API — see app/services/invoice_ledger.py."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services import invoice_ledger as ledger
from shared.auth import CurrentUser, get_current_user, require_role

router = APIRouter()

STAFF_ROLES = frozenset({"approver", "finance", "admin", "service"})


class InvoiceLineBody(BaseModel):
    description: str = ""
    quantity: float = Field(gt=0)
    unit_price: float = Field(ge=0)


class MatchBody(BaseModel):
    document_id: str
    vendor_id: str
    invoice_number: Optional[str] = None
    total: float = Field(gt=0)
    lines: list[InvoiceLineBody] = []
    payment_hold: bool = False
    hold_reason: Optional[str] = None
    # PO number printed on the invoice, e.g. "PO-9E085E38", if any.
    po_reference: Optional[str] = None


@router.post("/match", dependencies=[Depends(require_role("service", "finance", "admin"))])
async def match_invoice(body: MatchBody, dry_run: bool = False, db: AsyncSession = Depends(get_db),
                        user: CurrentUser = Depends(get_current_user)):
    """Books the invoice against the vendor's open purchase requests.
    Booking is for the document pipeline only (service token) — it spends
    a request's balance and moves its status, so a person could otherwise
    mark any request invoiced with a made-up document id. Finance/admin may
    only evaluate (dry_run=true, the match simulator)."""
    if not dry_run and user.role != "service":
        raise HTTPException(status_code=403, detail="only the document pipeline can book invoices; use dry_run=true")
    result = await ledger.book_invoice(
        db, document_id=body.document_id, vendor_id=body.vendor_id, invoice_number=body.invoice_number,
        total=body.total, lines=[ledger.InvoiceLine(l.description, l.quantity, l.unit_price) for l in body.lines],
        payment_hold=body.payment_hold, hold_reason=body.hold_reason, dry_run=dry_run, booked_by=user.email,
        po_ref=body.po_reference,
    )
    if not dry_run:
        await db.commit()
    return {"data": result.to_dict(), "meta": {"dry_run": dry_run}}


@router.post("/release-holds/{vendor_id}", dependencies=[Depends(require_role("service"))])
async def release_holds(vendor_id: str, db: AsyncSession = Depends(get_db)):
    """Called by document-vendor-agent after a vendor's bank details pass
    dual-control verification — the only way a hold should lift, so no
    human role may call it directly."""
    released = await ledger.release_payment_holds(db, vendor_id)
    await db.commit()
    return {"data": {"vendor_id": vendor_id, "released": released}}


@router.get("/ledger/{request_id}")
async def get_ledger(request_id: str, db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    owner = (await db.execute(text("SELECT requested_by FROM purchase_requests WHERE id = :id"), {"id": request_id})).scalar()
    if owner is None or (user.role not in STAFF_ROLES and owner.lower() != user.email.lower()):
        raise HTTPException(status_code=404, detail="request not found")
    data = await ledger.ledger_for_request(db, request_id)
    if not data:
        raise HTTPException(status_code=404, detail="request not found")
    return {"data": data}


@router.get("/matches", dependencies=[Depends(require_role("approver", "finance", "admin"))])
async def list_matches(status: Optional[str] = None, held: Optional[bool] = None, limit: int = 100,
                       db: AsyncSession = Depends(get_db)):
    where, params = [], {"limit": max(1, min(limit, 500))}
    if status:
        where.append("m.status = :status")
        params["status"] = status
    if held is not None:
        where.append("m.payment_hold = :held")
        params["held"] = held
    rows = (
        await db.execute(text(
            "SELECT m.document_id, m.vendor_id, v.name AS vendor_name, m.purchase_request_id, m.invoice_number, "
            "m.status, m.amount, m.payment_hold, m.hold_reason, m.result, m.created_at "
            "FROM invoice_matches m LEFT JOIN vendors v ON v.id = m.vendor_id "
            + (f"WHERE {' AND '.join(where)} " if where else "")
            + "ORDER BY m.created_at DESC LIMIT :limit"
        ), params)
    ).all()
    return {"data": [
        {"document_id": str(r.document_id), "vendor_id": str(r.vendor_id) if r.vendor_id else None,
         "vendor_name": r.vendor_name,
         "purchase_request_id": str(r.purchase_request_id) if r.purchase_request_id else None,
         "invoice_number": r.invoice_number, "status": r.status,
         "amount": float(r.amount) if r.amount is not None else None, "payment_hold": r.payment_hold,
         "hold_reason": r.hold_reason, "issues": (r.result or {}).get("issues", []),
         "created_at": r.created_at.isoformat()}
        for r in rows
    ]}
