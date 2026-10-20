"""Goods receipts (feature expansion Phase 3d): receiving 30 of 50 laptops
now and 20 next week.

Each delivery is a goods_receipts row with the quantity received per
purchase-request line (line numbers as invoice_ledger.po_lines_from_items
numbers them) and, for hardware, the asset tags or serial numbers of the
units. The first partial delivery moves an ordered request to
partially_received; the delivery that completes every line hands over to
consumer.apply_received, the same path as "Mark as received" (status
fulfilled, licences activated, stock released, seat add-ons applied, once).

The invoice ledger reads received_quantities(): once receiving has started
on a request, an invoice line asking for more than has been received is a
variance (rule invoice.match_against_received) — the third leg of the
three-way match.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.eventing import staged

RECEIVABLE = ("ordered", "partially_received", "partially_invoiced", "invoice_received")


class ReceiptError(ValueError):
    """The delivery can't be recorded (nothing ordered, more than ordered…)."""


async def receipts_for(db: AsyncSession, request_id: str) -> list:
    from app.models import GoodsReceipt
    return list((await db.execute(select(GoodsReceipt).where(GoodsReceipt.request_id == request_id)
                                  .order_by(GoodsReceipt.received_at))).scalars().all())


def total_received(receipts: list) -> dict[int, float]:
    out: dict[int, float] = {}
    for r in receipts:
        for line in r.lines or []:
            out[int(line["line_no"])] = out.get(int(line["line_no"]), 0) + float(line["quantity"])
    return out


async def received_quantities(db: AsyncSession, request_id: str) -> Optional[dict[int, float]]:
    """line_no -> quantity received so far, or None when nothing has been
    received through receipts (receiving hasn't started)."""
    receipts = await receipts_for(db, request_id)
    return total_received(receipts) if receipts else None


def outstanding(req, received: dict[int, float]) -> dict[int, float]:
    from app.services.invoice_ledger import po_lines_from_items
    return {pl.line_no: pl.quantity - received.get(pl.line_no, 0) for pl in po_lines_from_items(req.items)}


async def record_receipt(db: AsyncSession, req, lines: list[dict], received_by: str, producer=None,
                         notes: Optional[str] = None) -> tuple:
    """Records one delivery. Returns (receipt, outcome) where outcome is
    'partially_received' or apply_received's result when this delivery
    completed the request. Caller commits."""
    from app.kafka.consumer import NotReceivable, apply_received
    from app.models import GoodsReceipt

    if req.status not in RECEIVABLE:
        raise ReceiptError(f"request is '{req.status}': goods are received once its contract is signed (status 'ordered')")
    prior = await receipts_for(db, req.id)
    left = outstanding(req, total_received(prior))
    if not left:
        raise ReceiptError("this request has no line quantities to receive against; use Mark as received")
    if not any(q > 0 for q in left.values()):
        raise ReceiptError("everything on this request has already been received")
    clean = []
    for line in lines:
        try:
            line_no, qty = int(line["line_no"]), float(line["quantity"])
        except (KeyError, TypeError, ValueError):
            raise ReceiptError("each line needs a line_no and a quantity")
        if qty == 0:
            continue
        if line_no not in left:
            raise ReceiptError(f"line {line_no} is not on this request")
        if qty < 0 or qty != int(qty):
            raise ReceiptError("received quantities are whole numbers")
        if qty > left[line_no]:
            raise ReceiptError(f"line {line_no}: {int(qty)} received but only {int(left[line_no])} still to come")
        tags = [str(t).strip() for t in (line.get("asset_tags") or []) if str(t).strip()]
        if len(tags) > qty:
            raise ReceiptError(f"line {line_no}: more asset tags than units received")
        clean.append({"line_no": line_no, "quantity": int(qty), "asset_tags": tags})
    if not clean:
        raise ReceiptError("nothing received: enter a quantity for at least one line")

    now = datetime.now(timezone.utc)
    receipt = GoodsReceipt(id=str(uuid.uuid4()), request_id=req.id, lines=clean, received_by=received_by,
                           received_at=now, notes=notes)
    db.add(receipt)
    for c in clean:
        left[c["line_no"]] -= c["quantity"]
    complete = all(q <= 0 for q in left.values())
    if complete:
        try:
            outcome = await apply_received(db, req, received_by)
        except NotReceivable as e:
            raise ReceiptError(str(e))
    else:
        if req.status == "ordered":
            req.status = "partially_received"
        req.updated_at = now
        outcome = "partially_received"
    outbox = staged(producer, db)
    if outbox is not None:
        await outbox.publish_goods_received(req, receipt, complete)
    return receipt, outcome


async def receive_all(db: AsyncSession, req, received_by: str, producer=None) -> str:
    """"Mark as received": whatever is still outstanding arrives now. A
    request without line quantities (or already received through receipts)
    goes straight to apply_received, as before."""
    from app.kafka.consumer import apply_received
    if req.status in RECEIVABLE:
        left = outstanding(req, total_received(await receipts_for(db, req.id)))
        lines = [{"line_no": n, "quantity": q} for n, q in left.items() if q > 0]
        if lines:
            _, outcome = await record_receipt(db, req, lines, received_by, producer)
            return outcome
    return await apply_received(db, req, received_by)
