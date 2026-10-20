"""Invoice ledger: three-way match against what is still left to invoice.

Replaces the old match (document-vendor-agent asked for *approved*
requests of the same vendor whose total was within ±5% of the invoice
total), which had three holes:

  - it only looked at `approved` requests, but a request moves to
    `ordered` when its contract is signed — the usual time an invoice
    arrives — so those invoices could never match;
  - ±5% on the header total let a vendor overbill up to 5% on every
    invoice without anyone seeing it, and checked no lines or quantities;
  - one invoice consumed the whole request, so partial invoicing wasn't
    possible and a second invoice against the same PO wasn't caught.

Now each request has a balance: its amount and line quantities, minus
what earlier invoices already booked (invoice_allocations). An invoice
matches when every line maps to a PO line with enough quantity left, at a
unit price no higher than the PO's (plus a small rounding tolerance), and
its total fits in the remaining balance. Tolerance is asymmetric: paying
less than the PO is fine, paying more is always flagged.

evaluate() is pure; book_invoice() runs it inside a transaction that
row-locks the candidate requests, so two invoices can't both spend the
same balance.
"""
import difflib
import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, text

LINE_SIMILARITY_MIN = 0.55
MATCHABLE_STATUSES = ("approved", "ordered", "partially_received", "fulfilled", "partially_invoiced")


@dataclass
class POLine:
    line_no: int
    description: str
    quantity: float
    unit_price: float


@dataclass
class Candidate:
    request_id: str
    status: str
    amount: float
    lines: list[POLine]
    invoiced_amount: float = 0.0
    invoiced_qty: dict = field(default_factory=dict)  # line_no -> qty already invoiced
    created_at: Optional[str] = None
    # line_no -> qty received (goods receipts, Phase 3); None = receiving
    # hasn't started or rule invoice.match_against_received is off.
    received_qty: Optional[dict] = None

    @property
    def remaining_amount(self) -> float:
        return round(self.amount - self.invoiced_amount, 2)


@dataclass
class InvoiceLine:
    description: str
    quantity: float
    unit_price: float


@dataclass
class Tolerances:
    overbill_pct: float = 0.01     # invoice total may exceed the remaining balance by this much (rounding/tax)
    unit_price_pct: float = 0.01   # unit price may exceed the PO price by this much
    plausible_pct: float = 0.25    # how far off a PO can be and still be reported as "the one with a variance"


@dataclass
class MatchResult:
    status: str  # matched | partial | variance | ambiguous | no_match
    request_id: Optional[str] = None
    amount: float = 0.0
    allocations: list = field(default_factory=list)
    issues: list = field(default_factory=list)
    remaining_before: Optional[float] = None
    remaining_after: Optional[float] = None
    candidates: list = field(default_factory=list)
    notes: list = field(default_factory=list)  # for the reviewer; never change the status

    def to_dict(self) -> dict:
        return asdict(self)


def _norm(text_: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", (text_ or "").lower()).strip()


def _similarity(a: str, b: str) -> float:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def po_lines_from_items(items: Optional[list]) -> list[POLine]:
    lines = []
    for i, item in enumerate(items or []):
        try:
            qty = float(item.get("quantity") or 0)
            price = float(item.get("unit_price") or 0)
        except (TypeError, ValueError):
            continue
        desc = item.get("description") or item.get("name") or item.get("item_description") or ""
        if qty > 0:
            lines.append(POLine(i, desc, qty, price))
    return lines


def _evaluate_candidate(cand: Candidate, total: float, lines: list[InvoiceLine], tol: Tolerances):
    """-> (issues, allocations, lines_recognised)"""
    issues: list[str] = []
    allocations: list[dict] = []
    recognised = 0
    remaining_qty = {pl.line_no: pl.quantity - float(cand.invoiced_qty.get(pl.line_no, 0)) for pl in cand.lines}
    received_left = None if cand.received_qty is None else {
        pl.line_no: float(cand.received_qty.get(pl.line_no, 0)) - float(cand.invoiced_qty.get(pl.line_no, 0))
        for pl in cand.lines}

    if lines and cand.lines:
        for inv in lines:
            best = max(cand.lines, key=lambda pl: _similarity(inv.description, pl.description))
            if _similarity(inv.description, best.description) < LINE_SIMILARITY_MIN:
                issues.append(f"'{inv.description}' isn't on this purchase request")
                continue
            recognised += 1
            left = remaining_qty[best.line_no]
            if inv.quantity > left + 1e-6:
                issues.append(
                    f"'{best.description}': invoiced qty {inv.quantity:g} but only {max(left, 0):g} left to invoice"
                )
            if inv.unit_price > best.unit_price * (1 + tol.unit_price_pct) + 0.01:
                issues.append(
                    f"'{best.description}': unit price {inv.unit_price:,.2f} is above the agreed {best.unit_price:,.2f}"
                )
            if received_left is not None:
                # Three-way match: never pay for more than has arrived.
                got = received_left[best.line_no]
                if inv.quantity > got + 1e-6 and inv.quantity <= left + 1e-6:
                    issues.append(
                        f"'{best.description}': invoiced qty {inv.quantity:g} but only {max(got, 0):g} received "
                        f"and not yet invoiced"
                    )
                received_left[best.line_no] = got - inv.quantity
            remaining_qty[best.line_no] = left - inv.quantity
            allocations.append({
                "line_no": best.line_no, "description": best.description,
                "quantity": inv.quantity, "amount": round(inv.quantity * inv.unit_price, 2),
            })

    remaining = cand.remaining_amount
    if total > remaining * (1 + tol.overbill_pct) + 0.01:
        if remaining <= 0.01:
            issues.append("this purchase request has already been fully invoiced")
        else:
            issues.append(f"invoice total {total:,.2f} exceeds the {remaining:,.2f} left to invoice")
    if not allocations:
        allocations = [{"line_no": None, "description": "invoice total", "quantity": None, "amount": round(total, 2)}]
    else:
        # Line prices are pre-tax; request amounts and balances include tax.
        # Spread the invoice total over its lines so the ledger books what
        # the invoice actually charges.
        line_sum = sum(a["amount"] for a in allocations)
        if line_sum > 0:
            factor = total / line_sum
            for a in allocations:
                a["amount"] = round(a["amount"] * factor, 2)
            allocations[-1]["amount"] = round(allocations[-1]["amount"] + total - sum(a["amount"] for a in allocations), 2)
    return issues, allocations, recognised


def _po_ref_matches(po_ref: str, request_id: str) -> bool:
    ref = re.sub(r"[^a-z0-9]", "", po_ref.lower()).removeprefix("po")
    return bool(ref) and request_id.replace("-", "").lower().startswith(ref)


def evaluate(total: float, lines: list[InvoiceLine], candidates: list[Candidate], tol: Tolerances,
             po_ref: Optional[str] = None) -> MatchResult:
    if total is None or total <= 0:
        return MatchResult("no_match", issues=["invoice has no total"])
    if po_ref:
        # The invoice names its purchase order: that's the only candidate.
        referenced = [c for c in candidates if _po_ref_matches(po_ref, c.request_id)]
        if not referenced:
            return MatchResult(
                "no_match", amount=total,
                issues=[f"invoice references {po_ref}, which isn't an open purchase request for this vendor"],
            )
        candidates = referenced

    clean, flawed = [], []
    for cand in candidates:
        issues, allocations, recognised = _evaluate_candidate(cand, total, lines, tol)
        summary = {
            "request_id": cand.request_id, "status": cand.status,
            "remaining": cand.remaining_amount, "issues": issues,
        }
        if not issues:
            clean.append((cand, allocations, summary))
        else:
            plausible = recognised > 0 or (
                cand.remaining_amount > 0 and abs(total - cand.remaining_amount) <= cand.remaining_amount * tol.plausible_pct
            ) or cand.remaining_amount <= 0.01 and abs(total - cand.amount) <= cand.amount * tol.plausible_pct
            if plausible:
                flawed.append((cand, issues, recognised, summary))

    summaries = [c[2] for c in clean] + [f[3] for f in flawed]

    if len(clean) > 1:
        # Prefer the request this invoice settles exactly, then the oldest.
        exact = [c for c in clean if abs(total - c[0].remaining_amount) <= max(0.01, c[0].remaining_amount * tol.overbill_pct)]
        if len(exact) == 1:
            clean = exact
        else:
            return MatchResult(
                "ambiguous", amount=total, candidates=summaries,
                issues=[f"{len(clean)} purchase requests could take this invoice"],
            )

    if len(clean) == 1:
        cand, allocations, _ = clean[0]
        remaining_after = round(cand.remaining_amount - total, 2)
        fully = remaining_after <= max(0.01, cand.amount * tol.overbill_pct)
        return MatchResult(
            "matched" if fully else "partial", cand.request_id, round(total, 2), allocations, [],
            cand.remaining_amount, max(remaining_after, 0.0), summaries,
        )

    if flawed:
        cand, issues, _, _ = sorted(flawed, key=lambda f: (-f[2], len(f[1])))[0]
        return MatchResult(
            "variance", cand.request_id, round(total, 2), [], issues, cand.remaining_amount, None, summaries,
        )
    return MatchResult("no_match", amount=total, issues=["no purchase request for this vendor has a balance that fits"])


# --- database side -----------------------------------------------------------

def tolerances_from_rules() -> Tolerances:
    from shared.rules_engine import get_rule
    return Tolerances(
        overbill_pct=float(get_rule("invoice.overbill_tolerance_pct", fallback=0.01)),
        unit_price_pct=float(get_rule("invoice.unit_price_tolerance_pct", fallback=0.01)),
    )


async def _load_candidates(db, vendor_id: str, lock: bool) -> list:
    from app.models import PurchaseRequest
    stmt = (
        select(PurchaseRequest)
        .where(PurchaseRequest.vendor_id == vendor_id, PurchaseRequest.status.in_(MATCHABLE_STATUSES))
        .order_by(PurchaseRequest.created_at)
    )
    if lock:
        stmt = stmt.with_for_update()
    return list((await db.execute(stmt)).scalars().all())


async def _balances(db, request_ids: list[str]) -> dict:
    if not request_ids:
        return {}
    rows = (
        await db.execute(
            text(
                "SELECT purchase_request_id, line_no, sum(quantity) AS qty, sum(amount) AS amount "
                "FROM invoice_allocations WHERE purchase_request_id = ANY(CAST(:ids AS uuid[])) "
                "GROUP BY purchase_request_id, line_no"
            ),
            {"ids": request_ids},
        )
    ).all()
    out: dict = {}
    for r in rows:
        b = out.setdefault(str(r.purchase_request_id), {"amount": 0.0, "qty": {}})
        b["amount"] += float(r.amount or 0)
        if r.line_no is not None:
            b["qty"][r.line_no] = float(r.qty or 0)
    return out


async def _received(db, request_ids: list[str]) -> dict:
    """request_id -> {line_no: qty received} for requests with goods
    receipts (Phase 3), when rule invoice.match_against_received is on."""
    from shared.rules_engine import get_rule
    if not request_ids or not bool(get_rule("invoice.match_against_received", fallback=True)):
        return {}
    rows = (
        await db.execute(
            text(
                "SELECT g.request_id, (l->>'line_no')::int AS line_no, sum((l->>'quantity')::numeric) AS qty "
                "FROM goods_receipts g, jsonb_array_elements(g.lines::jsonb) l "
                "WHERE g.request_id = ANY(CAST(:ids AS uuid[])) GROUP BY g.request_id, line_no"
            ),
            {"ids": request_ids},
        )
    ).all()
    out: dict = {}
    for r in rows:
        out.setdefault(str(r.request_id), {})[r.line_no] = float(r.qty or 0)
    return out


def _candidate(req, balance: dict, received: Optional[dict] = None) -> Candidate:
    return Candidate(
        request_id=str(req.id), status=req.status, amount=float(req.amount or 0),
        lines=po_lines_from_items(req.items), invoiced_amount=balance.get("amount", 0.0),
        invoiced_qty=balance.get("qty", {}), created_at=req.created_at.isoformat() if req.created_at else None,
        received_qty=received,
    )


async def book_invoice(
    db, *, document_id: str, vendor_id: str, invoice_number: Optional[str], total: float,
    lines: list[InvoiceLine], payment_hold: bool = False, hold_reason: Optional[str] = None,
    dry_run: bool = False, booked_by: str = "document-vendor-agent", po_ref: Optional[str] = None,
) -> MatchResult:
    """Evaluates the invoice and, unless dry_run, books a match: records the
    allocations and moves the request to partially_invoiced /
    invoice_received. Idempotent per document_id. Caller commits."""
    from app.models import AuditLog, PurchaseRequest

    if not dry_run:
        prior = (
            await db.execute(
                text("SELECT result FROM invoice_matches WHERE document_id = :d AND status IN ('matched', 'partial')"),
                {"d": document_id},
            )
        ).first()
        if prior:
            data = prior.result if isinstance(prior.result, dict) else json.loads(prior.result)
            return MatchResult(**data)

    reqs = await _load_candidates(db, vendor_id, lock=not dry_run)
    balances = await _balances(db, [str(r.id) for r in reqs])
    received = await _received(db, [str(r.id) for r in reqs])
    result = evaluate(total, lines, [_candidate(r, balances.get(str(r.id), {}), received.get(str(r.id))) for r in reqs],
                      tolerances_from_rules(), po_ref)
    if result.request_id:
        result.notes = await expected_credit_notes(db, result.request_id)
    if dry_run:
        return result

    now = datetime.now(timezone.utc)
    if result.status in ("matched", "partial"):
        for alloc in result.allocations:
            await db.execute(
                text(
                    "INSERT INTO invoice_allocations (id, document_id, purchase_request_id, invoice_number, line_no, "
                    "description, quantity, amount, payment_hold, created_at) VALUES "
                    "(:id, :doc, :req, :num, :line, :desc, :qty, :amount, :hold, :now)"
                ),
                {
                    "id": str(uuid.uuid4()), "doc": document_id, "req": result.request_id, "num": invoice_number,
                    "line": alloc["line_no"], "desc": alloc["description"], "qty": alloc["quantity"],
                    "amount": alloc["amount"], "hold": payment_hold, "now": now,
                },
            )
        req = next(r for r in reqs if str(r.id) == result.request_id)
        req.status = "invoice_received" if result.status == "matched" else "partially_invoiced"
        req.updated_at = now

    await db.execute(
        text(
            "INSERT INTO invoice_matches (document_id, vendor_id, purchase_request_id, invoice_number, status, "
            "amount, payment_hold, hold_reason, result, created_at) VALUES (:doc, :vendor, :req, :num, :status, "
            ":amount, :hold, :reason, CAST(:result AS JSONB), :now) "
            "ON CONFLICT (document_id) DO UPDATE SET purchase_request_id = EXCLUDED.purchase_request_id, "
            "status = EXCLUDED.status, amount = EXCLUDED.amount, payment_hold = EXCLUDED.payment_hold, "
            "hold_reason = EXCLUDED.hold_reason, result = EXCLUDED.result, created_at = EXCLUDED.created_at"
        ),
        {
            "doc": document_id, "vendor": vendor_id, "req": result.request_id, "num": invoice_number,
            "status": result.status, "amount": total, "hold": payment_hold, "reason": hold_reason,
            "result": json.dumps(result.to_dict(), default=str), "now": now,
        },
    )
    if result.request_id:
        db.add(AuditLog(
            id=str(uuid.uuid4()), entity_type="purchase_request", entity_id=result.request_id,
            action=f"invoice_{result.status}", performed_by=booked_by, created_at=now,
            details={"document_id": document_id, "invoice_number": invoice_number, "amount": total,
                     "issues": result.issues, "payment_hold": payment_hold},
        ))
    return result


async def expected_credits(db, request_id: str) -> list:
    """SLA service credits contract-risk-agent recorded against this request
    (feature expansion Phase 2) that the vendor hasn't applied yet. The
    table belongs to contract-risk-agent; before its migration has run
    there is nothing to read."""
    try:
        async with db.begin_nested():
            rows = (await db.execute(text(
                "SELECT id, period, credit_amount, currency FROM sla_credits "
                "WHERE purchase_request_id = :r AND status = 'expected' ORDER BY period"), {"r": request_id})).all()
    except Exception:
        return []
    return [{"id": str(r.id), "period": r.period, "amount": float(r.credit_amount), "currency": r.currency} for r in rows]


async def expected_credit_notes(db, request_id: str) -> list[str]:
    credits = await expected_credits(db, request_id)
    if not credits:
        return []
    total = round(sum(c["amount"] for c in credits), 2)
    periods = ", ".join(c["period"] for c in credits)
    return [f"SLA service credit of {credits[0]['currency']} {total:,.2f} ({periods}) is still expected from this "
            f"vendor; check this invoice deducts it before paying"]


async def release_payment_holds(db, vendor_id: str) -> int:
    res = await db.execute(
        text("UPDATE invoice_matches SET payment_hold = false, hold_reason = NULL WHERE vendor_id = :v AND payment_hold"),
        {"v": vendor_id},
    )
    await db.execute(
        text("UPDATE invoice_allocations SET payment_hold = false WHERE payment_hold AND document_id IN "
             "(SELECT document_id FROM invoice_matches WHERE vendor_id = :v)"),
        {"v": vendor_id},
    )
    return res.rowcount


async def ledger_for_request(db, request_id: str) -> dict:
    from app.models import PurchaseRequest
    req = (await db.execute(select(PurchaseRequest).where(PurchaseRequest.id == request_id))).scalar_one_or_none()
    if req is None:
        return {}
    balance = (await _balances(db, [request_id])).get(request_id, {"amount": 0.0, "qty": {}})
    received = (await _received(db, [request_id])).get(request_id)
    cand = _candidate(req, balance, received)
    invoices = (
        await db.execute(
            text("SELECT document_id, invoice_number, status, amount, payment_hold, hold_reason, created_at "
                 "FROM invoice_matches WHERE purchase_request_id = :r ORDER BY created_at"),
            {"r": request_id},
        )
    ).all()
    return {
        "request_id": request_id, "status": req.status, "amount": cand.amount,
        "expected_credits": await expected_credits(db, request_id),
        "invoiced_amount": round(cand.invoiced_amount, 2), "remaining_amount": cand.remaining_amount,
        "lines": [
            {"line_no": pl.line_no, "description": pl.description, "quantity": pl.quantity,
             "unit_price": pl.unit_price, "invoiced_quantity": float(cand.invoiced_qty.get(pl.line_no, 0)),
             "received_quantity": float(received.get(pl.line_no, 0)) if received is not None else None}
            for pl in cand.lines
        ],
        "invoices": [
            {"document_id": str(i.document_id), "invoice_number": i.invoice_number, "status": i.status,
             "amount": float(i.amount) if i.amount is not None else None, "payment_hold": i.payment_hold,
             "hold_reason": i.hold_reason, "created_at": i.created_at.isoformat()}
            for i in invoices
        ],
    }
