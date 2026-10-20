"""RFQ events and quote comparison (feature expansion Phase 3b).

For a larger purchase the buyer (finance or admin) invites several vendors
to quote by a deadline, compares the quotes on weighted criteria, can run a
second round with a shortlist, and awards one: the award becomes an
ordinary purchase request (budget check and approval included).

  open       invitations out, quotes coming in. Sealed RFQs show only *who*
             has responded, never amounts, to every role, until the deadline.
  closed     deadline passed (or everyone invited answered): comparison open
  awarded    a purchase request was created from the winning response
  cancelled

Quotes arrive the way they already do: a vendor e-mails or drops a quote
that quotes the RFQ reference ("RFQ-3F9A2C"); the document pipeline saves it
in vendor_quotes, and sweep_quotes() links it to the RFQ as a response.
A buyer can also record a response by hand (a quote read over the phone,
a portal screenshot).

Scoring (score()): each criterion is scored 0..1 among the current round's
responses and weighted by rule sourcing.default_criteria:
  price            cheapest total / this total
  lead_time        shortest lead time / this one
  warranty         this warranty / longest warranty
  support          the buyer's 1-5 rating of the support terms / 5
  vendor_risk      Low 1.0, Medium 0.6, High 0.2 (contract-risk-agent's band)
  delivery_record  on-time delivery rate from the vendor scorecard (Phase 3c)
Something not stated or not known yet counts as average (0.5), so a vendor
is neither rewarded nor punished for a blank.
"""
import logging
import re
import secrets
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.eventing import staged
from shared.rules_engine import get_rule

logger = logging.getLogger(__name__)

CRITERIA = ("price", "lead_time", "warranty", "support", "vendor_risk", "delivery_record")
DEFAULT_CRITERIA = {"price": 0.45, "lead_time": 0.15, "warranty": 0.1, "support": 0.1,
                    "vendor_risk": 0.1, "delivery_record": 0.1}
RISK_SCORE = {"Low": 1.0, "Medium": 0.6, "High": 0.2}
UNKNOWN = 0.5
MIN_VENDORS = 2
RFQ_REF = re.compile(r"\bRFQ-([0-9A-F]{6})\b", re.IGNORECASE)
QUOTE_SWEEP_SECONDS = 30


class SourcingError(Exception):
    def __init__(self, message: str, code: str = "rfq_rejected", status: int = 422):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def valid_criteria(weights) -> bool:
    return bool(isinstance(weights, dict) and weights and set(weights) <= set(CRITERIA)
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 for v in weights.values())
            and abs(sum(weights.values()) - 1) < 0.001)


def default_criteria() -> dict:
    weights = get_rule("sourcing.default_criteria", fallback=DEFAULT_CRITERIA)
    return dict(weights) if valid_criteria(weights) else dict(DEFAULT_CRITERIA)


def sealed_now(rfq, now: Optional[datetime] = None) -> bool:
    return bool(rfq.sealed) and rfq.status == "open" and (now or _now()) < rfq.deadline


def rfq_flag(amount: float, *, spends_money: bool, all_catalog: bool, from_rfq: bool) -> Optional[dict]:
    """The advisory note for a request above sourcing.rfq_required_above_inr
    that has neither an RFQ behind it nor a catalog price (0 = off)."""
    above = float(get_rule("sourcing.rfq_required_above_inr", fallback=200000) or 0)
    if above <= 0 or amount <= above or from_rfq or all_catalog or not spends_money:
        return None
    return {"code": "rfq_recommended",
            "message": f"Above ₹{above:,.0f} with no RFQ or catalog price: compare quotes from at least three "
                       f"vendors before approving"}


# ── scoring (pure) ───────────────────────────────────────────────────────────

def score(responses: list[dict], weights: dict, vendor_info: dict) -> list[dict]:
    """responses: [{id, vendor_id, total_inr, lead_time_days, warranty_months,
    support_rating}]; vendor_info: {vendor_id: {risk_band, on_time_rate}}.
    Returns them with per-criterion scores, total_score and rank (1 = best)."""
    if not responses:
        return []
    totals = [float(r["total_inr"]) for r in responses if float(r["total_inr"]) > 0]
    leads = [r["lead_time_days"] for r in responses if r.get("lead_time_days") is not None]
    warranties = [r["warranty_months"] for r in responses if r.get("warranty_months") is not None]
    cheapest, fastest, longest = (min(totals) if totals else 0), (min(leads) if leads else None), (max(warranties) if warranties else 0)
    out = []
    for r in responses:
        info = vendor_info.get(str(r["vendor_id"]), {})
        total = float(r["total_inr"])
        lead, warranty, rating = r.get("lead_time_days"), r.get("warranty_months"), r.get("support_rating")
        s = {
            "price": round(cheapest / total, 4) if total > 0 else 1.0,
            "lead_time": UNKNOWN if lead is None else (1.0 if lead <= 0 else round((fastest if fastest and fastest > 0 else lead) / lead, 4)),
            "warranty": UNKNOWN if warranty is None else (round(warranty / longest, 4) if longest > 0 else 1.0),
            "support": UNKNOWN if rating is None else round(rating / 5, 4),
            "vendor_risk": RISK_SCORE.get(info.get("risk_band"), UNKNOWN),
            "delivery_record": UNKNOWN if info.get("on_time_rate") is None else round(float(info["on_time_rate"]), 4),
        }
        out.append({**r, "scores": s, "total_score": round(sum(weights.get(k, 0) * v for k, v in s.items()), 4)})
    for rank, r in enumerate(sorted(out, key=lambda x: (-x["total_score"], float(x["total_inr"]))), start=1):
        r["rank"] = rank
    return sorted(out, key=lambda x: x["rank"])


# ── database side ───────────────────────────────────────────────────────────

async def vendor_info(db: AsyncSession, vendor_ids: list) -> dict:
    from app.services.budget_service import vendor_risk_band
    out = {}
    for vid in {str(v) for v in vendor_ids}:
        out[vid] = {"risk_band": await vendor_risk_band(db, vid), "on_time_rate": None}
    try:
        async with db.begin_nested():
            rows = (await db.execute(text(
                "SELECT vendor_id, on_time_rate FROM vendor_scorecards WHERE vendor_id = ANY(CAST(:ids AS uuid[]))"),
                {"ids": list(out)})).all()
        for r in rows:
            out[str(r.vendor_id)]["on_time_rate"] = float(r.on_time_rate) if r.on_time_rate is not None else None
    except Exception:
        pass  # contract-risk-agent's scorecard table isn't there yet
    return out


def _audit(db, rfq_id: str, action: str, actor: str, details: dict):
    from app.models import AuditLog
    db.add(AuditLog(id=str(uuid.uuid4()), entity_type="rfq", entity_id=rfq_id, action=action,
                    performed_by=actor, created_at=_now(), details=details))


async def _new_reference(db: AsyncSession) -> str:
    from app.models import RfqEvent
    for _ in range(20):
        ref = f"RFQ-{secrets.token_hex(3).upper()}"
        if (await db.execute(select(RfqEvent.id).where(RfqEvent.reference == ref))).first() is None:
            return ref
    raise SourcingError("could not allocate an RFQ reference", status=500)


async def _vendors_exist(db: AsyncSession, vendor_ids: list) -> None:
    from app.models import Vendor
    found = {str(v) for (v,) in (await db.execute(select(Vendor.id).where(Vendor.id.in_(vendor_ids)))).all()}
    missing = set(map(str, vendor_ids)) - found
    if missing:
        raise SourcingError(f"unknown vendor {sorted(missing)[0]}")


async def _invite(db, producer, rfq, vendor_ids: list):
    from app.models import RfqInvitation
    now = _now()
    for vid in vendor_ids:
        db.add(RfqInvitation(rfq_id=rfq.id, vendor_id=vid, round=rfq.round, invited_at=now))
    outbox = staged(producer, db)
    if outbox is not None:
        await outbox.publish_rfq_issued(rfq, vendor_ids)


async def create_rfq(db: AsyncSession, producer, actor: str, *, title: str, department: str, request_type: str,
                     items: list, vendor_ids: list, deadline: datetime, sealed: bool = True,
                     criteria: Optional[dict] = None):
    from app.models import RfqEvent
    vendor_ids = list(dict.fromkeys(str(v) for v in vendor_ids))
    if len(vendor_ids) < MIN_VENDORS:
        raise SourcingError(f"invite at least {MIN_VENDORS} vendors (three or more is usual)")
    if deadline <= _now():
        raise SourcingError("the deadline must be in the future")
    if criteria is not None and not valid_criteria(criteria):
        raise SourcingError(f"criteria are weights for {', '.join(CRITERIA)} that add up to 1")
    await _vendors_exist(db, vendor_ids)
    now = _now()
    rfq = RfqEvent(id=str(uuid.uuid4()), reference=await _new_reference(db), title=title, department=department,
                   request_type=request_type, items=items, criteria=criteria or default_criteria(), sealed=sealed,
                   round=1, deadline=deadline, status="open", created_by=actor, created_at=now, updated_at=now)
    db.add(rfq)
    await db.flush()
    await _invite(db, producer, rfq, vendor_ids)
    _audit(db, rfq.id, "rfq_issued", actor, {"reference": rfq.reference, "vendors": vendor_ids,
                                              "deadline": deadline.isoformat(), "sealed": sealed})
    return rfq


async def invitations(db: AsyncSession, rfq_id: str, round_: Optional[int] = None) -> list:
    from app.models import RfqInvitation
    q = select(RfqInvitation).where(RfqInvitation.rfq_id == rfq_id)
    if round_ is not None:
        q = q.where(RfqInvitation.round == round_)
    return list((await db.execute(q.order_by(RfqInvitation.round, RfqInvitation.invited_at))).scalars().all())


async def responses(db: AsyncSession, rfq_id: str) -> list:
    from app.models import RfqResponse
    return list((await db.execute(select(RfqResponse).where(RfqResponse.rfq_id == rfq_id)
                                  .order_by(RfqResponse.round, RfqResponse.submitted_at))).scalars().all())


async def record_response(db: AsyncSession, rfq, vendor_id: str, *, total_inr: float, actor: str,
                          lead_time_days: Optional[int] = None, warranty_months: Optional[int] = None,
                          support_rating: Optional[int] = None, support_terms: Optional[str] = None,
                          line_items: Optional[list] = None, source: str = "manual", quote_id: Optional[str] = None):
    """A vendor's quote for the current round. A second quote from the same
    vendor before the deadline replaces the first (a revised offer)."""
    from app.models import RfqInvitation, RfqResponse
    now = _now()
    if rfq.status != "open":
        raise SourcingError(f"the RFQ is {rfq.status}; it no longer takes quotes")
    if now >= rfq.deadline:
        raise SourcingError("the deadline has passed; quotes after it are not accepted")
    inv = await db.get(RfqInvitation, (rfq.id, str(vendor_id), rfq.round))
    if inv is None:
        raise SourcingError("this vendor isn't invited to the current round")
    if total_inr is None or total_inr <= 0:
        raise SourcingError("a quote needs a total above zero")
    existing = (await db.execute(select(RfqResponse).where(
        RfqResponse.rfq_id == rfq.id, RfqResponse.vendor_id == str(vendor_id), RfqResponse.round == rfq.round))).scalars().first()
    resp = existing or RfqResponse(id=str(uuid.uuid4()), rfq_id=rfq.id, vendor_id=str(vendor_id), round=rfq.round)
    resp.total_inr, resp.lead_time_days, resp.warranty_months = round(float(total_inr), 2), lead_time_days, warranty_months
    resp.support_rating, resp.support_terms, resp.line_items = support_rating, support_terms, line_items or []
    resp.source, resp.quote_id, resp.submitted_by, resp.submitted_at = source, quote_id, actor, now
    if existing is None:
        db.add(resp)
    inv.responded_at = now
    rfq.updated_at = now
    # Sealed: the audit trail records that a quote came in, not its amount.
    _audit(db, rfq.id, "rfq_response_recorded", actor,
           {"vendor_id": str(vendor_id), "round": rfq.round, "source": source, "revised": existing is not None})
    return resp


async def close(db: AsyncSession, rfq, actor: str, now: Optional[datetime] = None):
    now = now or _now()
    if rfq.status != "open":
        raise SourcingError(f"the RFQ is already {rfq.status}")
    invited = await invitations(db, rfq.id, rfq.round)
    everyone = invited and all(i.responded_at for i in invited)
    if now < rfq.deadline and not everyone:
        raise SourcingError("it can close at the deadline, or earlier once every invited vendor has quoted")
    rfq.status, rfq.updated_at = "closed", now
    _audit(db, rfq.id, "rfq_closed", actor, {"round": rfq.round, "early": now < rfq.deadline})
    return rfq


async def close_if_due(db: AsyncSession, rfq) -> bool:
    if rfq.status == "open" and _now() >= rfq.deadline:
        await close(db, rfq, "system")
        return True
    return False


async def extend(db: AsyncSession, rfq, deadline: datetime, actor: str):
    if rfq.status != "open":
        raise SourcingError("only an open RFQ's deadline can move")
    if deadline <= max(_now(), rfq.deadline):
        raise SourcingError("the new deadline must be later than the current one")
    _audit(db, rfq.id, "rfq_extended", actor, {"from": rfq.deadline.isoformat(), "to": deadline.isoformat()})
    rfq.deadline, rfq.updated_at = deadline, _now()
    return rfq


async def next_round(db: AsyncSession, producer, rfq, vendor_ids: list, deadline: datetime, actor: str):
    """A second (third…) round for a shortlist of this round's responders.
    Earlier rounds' quotes stay for reference."""
    await close_if_due(db, rfq)
    if rfq.status != "closed":
        raise SourcingError("close this round before starting the next")
    answered = {str(r.vendor_id) for r in await responses(db, rfq.id) if r.round == rfq.round}
    vendor_ids = list(dict.fromkeys(str(v) for v in vendor_ids))
    if len(vendor_ids) < 1 or not set(vendor_ids) <= answered:
        raise SourcingError("the shortlist is vendors who quoted in this round")
    if deadline <= _now():
        raise SourcingError("the deadline must be in the future")
    rfq.round, rfq.deadline, rfq.status, rfq.updated_at = rfq.round + 1, deadline, "open", _now()
    await _invite(db, producer, rfq, vendor_ids)
    _audit(db, rfq.id, "rfq_next_round", actor, {"round": rfq.round, "vendors": vendor_ids})
    return rfq


def _request_items(rfq, resp) -> list:
    """The winning quote's lines when it has priced lines; otherwise the
    RFQ's items with the quoted total spread evenly over the units."""
    priced = [li for li in (resp.line_items or []) if li.get("quantity") and li.get("unit_price") is not None]
    if priced:
        return [{"name": li.get("description") or li.get("name") or "Item", "description": li.get("description") or li.get("name"),
                 "quantity": li["quantity"], "unit_price": li["unit_price"]} for li in priced]
    units = sum(float(i.get("quantity") or 1) for i in rfq.items) or 1
    return [{"name": i.get("name"), "description": i.get("name"), "quantity": i.get("quantity") or 1,
             "unit_price": round(float(resp.total_inr) / units, 2)} for i in rfq.items]


async def award(db: AsyncSession, approval_svc, producer, rfq, response_id: str, actor: str):
    """Creates the purchase request from the winning response (normal
    budget check and approval) and marks the RFQ awarded."""
    from app.models import RfqResponse
    from app.schemas import CreatePurchaseRequest
    await close_if_due(db, rfq)
    if rfq.status != "closed":
        raise SourcingError("an RFQ is awarded after it closes")
    resp = await db.get(RfqResponse, response_id)
    if resp is None or resp.rfq_id != rfq.id or resp.round != rfq.round:
        raise SourcingError("that response isn't in this RFQ's latest round")
    document_id = None
    if resp.quote_id:
        document_id = (await db.execute(text("SELECT document_id FROM vendor_quotes WHERE id = :q"),
                                        {"q": resp.quote_id})).scalar()
    # Claim the RFQ before create_request (which commits on its own), so a
    # second award at the same moment finds it already awarded.
    rfq.status, rfq.awarded_response_id = "awarded", resp.id
    await db.commit()
    data = CreatePurchaseRequest(
        request_type=rfq.request_type, requested_by=actor, department=rfq.department, vendor_id=str(resp.vendor_id),
        document_id=str(document_id) if document_id else None, amount=float(resp.total_inr), currency="INR",
        items=_request_items(rfq, resp), comments=f"Awarded from {rfq.reference}: {rfq.title}")
    try:
        req = await approval_svc.create_request(data, document_id=data.document_id, rfq_id=rfq.id)
    except Exception:
        await db.rollback()
        rfq.status, rfq.awarded_response_id = "closed", None
        await db.commit()
        raise
    losers = sorted({str(i.vendor_id) for i in await invitations(db, rfq.id)} - {str(resp.vendor_id)})
    rfq.status, rfq.updated_at = "awarded", _now()
    rfq.awarded_vendor_id, rfq.awarded_response_id, rfq.awarded_request_id = resp.vendor_id, resp.id, req.id
    _audit(db, rfq.id, "rfq_awarded", actor, {"vendor_id": str(resp.vendor_id), "total_inr": float(resp.total_inr),
                                              "request_id": str(req.id)})
    outbox = staged(producer, db)
    if outbox is not None:
        await outbox.publish_rfq_awarded(rfq, resp, req.id, losers)
    return req


async def cancel(db: AsyncSession, rfq, actor: str, reason: str):
    if rfq.status in ("awarded", "cancelled"):
        raise SourcingError(f"the RFQ is already {rfq.status}")
    if not (reason or "").strip():
        raise SourcingError("say why the RFQ is cancelled")
    rfq.status, rfq.updated_at = "cancelled", _now()
    _audit(db, rfq.id, "rfq_cancelled", actor, {"reason": reason})
    return rfq


# ── quotes that quote an RFQ reference ──────────────────────────────────────

def find_rfq_reference(text_: Optional[str]) -> Optional[str]:
    m = RFQ_REF.search(text_ or "")
    return f"RFQ-{m.group(1).upper()}" if m else None


async def sweep_quotes(session_factory) -> int:
    """Links quotes saved by the document pipeline that quote an open RFQ's
    reference. A quote from a vendor that wasn't invited, or after the
    deadline, is left alone (a buyer can still enter it by hand)."""
    from app.models import RfqEvent
    linked = 0
    async with session_factory() as db:
        rows = (await db.execute(text(
            "SELECT q.id, q.vendor_id, q.total, q.currency, q.line_items, q.raw_text FROM vendor_quotes q "
            "WHERE q.raw_text ~* 'RFQ-[0-9A-F]{6}' AND q.vendor_id IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM rfq_responses r WHERE r.quote_id = q.id) "
            "AND EXISTS (SELECT 1 FROM rfq_events e WHERE e.status = 'open' AND e.deadline > now() "
            "            AND q.raw_text ILIKE '%' || e.reference || '%') "
            "AND q.created_at > now() - interval '60 days' ORDER BY q.created_at LIMIT 50"))).all()
        for q in rows:
            ref = find_rfq_reference(q.raw_text)
            rfq = (await db.execute(select(RfqEvent).where(RfqEvent.reference == ref))).scalars().first()
            if rfq is None or (q.currency or "INR") != "INR" or q.total is None:
                continue
            try:
                await record_response(db, rfq, str(q.vendor_id), total_inr=float(q.total), actor="document-pipeline",
                                      line_items=q.line_items or [], source="quote", quote_id=str(q.id))
                await db.commit()
                linked += 1
            except SourcingError as e:
                await db.rollback()
                logger.info(f"Quote {q.id} quotes {ref} but wasn't linked: {e.message}")
    return linked


async def run_quote_sweep(session_factory):
    import asyncio
    while True:
        try:
            await sweep_quotes(session_factory)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"RFQ quote sweep failed: {e}", exc_info=True)
        await asyncio.sleep(QUOTE_SWEEP_SECONDS)
