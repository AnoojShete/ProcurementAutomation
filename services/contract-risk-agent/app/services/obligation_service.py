"""Contract obligations after signature (feature expansion Phase 2).

Lifecycle of an obligation:
  to_confirm  extracted from a signed contract by obligation_extraction.py
              (rules, or Legal-BERT where it won on CUAD); nothing happens
              until a person confirms it
  open        confirmed: it has an owner and, where the type has one, a due
              date; reminders go out before it (rule contract.obligation_reminder_days)
  met         done (one-off types); recurring ones (monthly SLA review,
              yearly audit window) roll to the next due date instead
  breached    the licence has more users than the contract allows (checked
              by the sweep), or a person recorded a breach
  waived      deliberately not pursued, with a reason

SLA downtime: recording a month's measured uptime computes the service
credit from the confirmed credit terms; the credit is then expected on the
vendor's next invoice (approval-inventory-agent's invoice ledger warns
when an invoice is booked while a credit is still expected).

Every change is an obligation_events row; reminders and breaches are
published as contract.obligation.due through the outbox.
"""
import asyncio
import logging
import uuid
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from dateutil.relativedelta import relativedelta
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Contract, ContractObligation, ObligationEvent, PurchaseRequest, SlaCredit
from app.services import obligation_extraction as ox
from app.services.audit import write_audit_log
from shared.eventing import staged
from shared.rules_engine import get_rule

logger = logging.getLogger(__name__)
SWEEP_SECONDS = 60
EXTRACT_PER_SWEEP = 3


class ObligationError(Exception):
    """A request the obligation can't take (wrong status, missing terms)."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _month_end(d: date) -> date:
    return d.replace(day=monthrange(d.year, d.month)[1])


def reminder_days() -> list[int]:
    days = get_rule("contract.obligation_reminder_days", fallback=[30, 7])
    return sorted({d for d in days if isinstance(d, int) and d > 0}, reverse=True) if isinstance(days, list) else [30, 7]


def first_due(ob: ContractObligation, contract: Contract, today: date) -> tuple[Optional[date], str]:
    """(due_date, recurrence) when an obligation is confirmed."""
    signed = (contract.signed_at or _now()).date()
    v = ob.value or {}
    match ob.type:
        case "sla_uptime":
            return _month_end(today), "monthly"
        case "audit_rights":
            due = signed + relativedelta(years=1)
            while due < today:
                due += relativedelta(years=1)
            return due, "annual"
        case "warranty":
            return (signed + relativedelta(months=int(v["months"])) if v.get("months") else None), "none"
        case "minimum_commitment":
            return (signed + relativedelta(months=int(v["months"])) if v.get("months") else None), "none"
        case "price_cap":
            return contract.contract_end_date, "none"
        case "post_termination":
            end = contract.contract_end_date
            return (end + timedelta(days=int(v.get("days") or 0)) if end else None), "none"
    return None, "none"


def next_due(ob: ContractObligation) -> Optional[date]:
    if ob.due_date is None:
        return None
    if ob.recurrence == "monthly":
        return _month_end(ob.due_date + timedelta(days=1))
    if ob.recurrence == "annual":
        return ob.due_date + relativedelta(years=1)
    return None


def _event(db: AsyncSession, ob: ContractObligation, kind: str, actor: Optional[str], details: Optional[dict] = None):
    db.add(ObligationEvent(id=str(uuid.uuid4()), obligation_id=ob.id, kind=kind, details=details or {},
                           performed_by=actor, created_at=_now()))


# ── extraction ───────────────────────────────────────────────────────────────

async def extract_for_contract(db: AsyncSession, contract: Contract, actor: str = "obligation-sweep") -> list[ContractObligation]:
    """Reads the contract and adds a to_confirm obligation for every type
    found that the contract doesn't have yet. The caller commits."""
    from app.services import clause_model
    use_model = bool(ox.MODEL_TYPES) and await asyncio.to_thread(clause_model.available)
    min_score = float(get_rule("contract.obligation_model_min_confidence", fallback=0.5))
    found = await asyncio.to_thread(ox.extract_obligations, contract.contract_text or "", use_model, min_score)
    existing = {t for (t,) in (await db.execute(
        select(ContractObligation.type).where(ContractObligation.contract_id == contract.id))).all()}
    now = _now()
    created = []
    for o in found:
        if o["type"] in existing:
            continue
        ob = ContractObligation(
            id=str(uuid.uuid4()), contract_id=contract.id, type=o["type"], clause_text=o["clause_text"],
            value=o["value"], status="to_confirm", recurrence=ox.TYPES[o["type"]].recurrence,
            extracted_by=o["extracted_by"], confidence=o["confidence"], created_at=now, updated_at=now)
        db.add(ob)
        await db.flush()
        _event(db, ob, "extracted", actor, {"extracted_by": o["extracted_by"], "value": o["value"]})
        created.append(ob)
    contract.obligations_extracted_at = now
    await write_audit_log(db, "contract", contract.id, "obligations_extracted",
                          {"found": [o["type"] for o in found], "added": [o.type for o in created],
                           "model_used": use_model})
    return created


async def sweep_extraction(session_factory) -> int:
    """Signed contracts not read yet. Runs every minute, a few at a time."""
    async with session_factory() as db:
        contracts = (await db.execute(
            select(Contract).where(Contract.status == "signed", Contract.obligations_extracted_at.is_(None))
            .order_by(Contract.signed_at).limit(EXTRACT_PER_SWEEP))).scalars().all()
        n = 0
        for contract in contracts:
            n += len(await extract_for_contract(db, contract))
            await db.commit()
        return n


# ── people's actions ─────────────────────────────────────────────────────────

async def confirm(db: AsyncSession, ob: ContractObligation, actor: str, *, value: Optional[dict] = None,
                  owner_email: Optional[str] = None, license_id: Optional[str] = None,
                  due_date: Optional[date] = None) -> ContractObligation:
    if ob.status not in ("to_confirm", "open", "breached"):
        raise ObligationError(f"an obligation that is {ob.status} can't be confirmed")
    contract = await db.get(Contract, ob.contract_id)
    if contract is None or contract.status != "signed":
        raise ObligationError("obligations are confirmed on signed contracts")
    changes = {}
    if value is not None and value != ob.value:
        changes["value"] = {"from": ob.value, "to": value}
        ob.value = value
    if owner_email is not None:
        ob.owner_email = owner_email or None
    if license_id is not None:
        ob.license_id = license_id or None
    if ob.type == "license_limit" and ob.license_id and not (ob.value or {}).get("seats"):
        raise ObligationError("a licence limit linked to a licence needs a seat number")
    computed, recurrence = first_due(ob, contract, _now().date())
    ob.due_date = due_date or computed
    ob.recurrence = recurrence
    first_time = ob.status == "to_confirm"
    ob.status = "open"
    ob.confirmed_by, ob.confirmed_at, ob.updated_at = actor, _now(), _now()
    _event(db, ob, "confirmed" if first_time else "edited", actor,
           {**changes, "due_date": ob.due_date.isoformat() if ob.due_date else None,
            "owner_email": ob.owner_email, "license_id": ob.license_id})
    return ob


async def record(db: AsyncSession, ob: ContractObligation, kind: str, actor: str, note: Optional[str] = None) -> ContractObligation:
    """met | waived | reopened | breach."""
    if ob.status == "to_confirm" and kind != "waived":
        raise ObligationError("confirm the obligation first")
    if kind == "met":
        if ob.status not in ("open", "breached"):
            raise ObligationError(f"an obligation that is {ob.status} can't be marked met")
        nxt = next_due(ob)
        details = {"note": note, "for_due_date": ob.due_date.isoformat() if ob.due_date else None}
        if nxt:  # recurring: done for this period, open for the next
            ob.due_date, ob.status = nxt, "open"
            details["next_due_date"] = nxt.isoformat()
        else:
            ob.status = "met"
        _event(db, ob, "met", actor, details)
    elif kind == "waived":
        if not (note or "").strip():
            raise ObligationError("say why the obligation is waived")
        ob.status = "waived"
        _event(db, ob, "waived", actor, {"note": note})
    elif kind == "reopened":
        if ob.status not in ("met", "waived", "breached"):
            raise ObligationError("only met, waived or breached obligations can be reopened")
        ob.status = "open"
        _event(db, ob, "reopened", actor, {"note": note})
    elif kind == "breach":
        ob.status = "breached"
        _event(db, ob, "breach", actor, {"note": note, "source": "manual"})
    else:
        raise ObligationError(f"unknown action {kind}")
    ob.updated_at = _now()
    return ob


async def monthly_fee(db: AsyncSession, contract: Contract) -> tuple[float, str]:
    """The contract's value per month: its purchase request amount over 12
    (the SaaS template's fee is annual)."""
    pr = await db.get(PurchaseRequest, contract.purchase_request_id) if contract.purchase_request_id else None
    if pr is None or pr.amount is None:
        return 0.0, "INR"
    return round(float(pr.amount) / 12, 2), pr.currency or "INR"


async def record_downtime(db: AsyncSession, ob: ContractObligation, period: str, measured_uptime_pct: float,
                          actor: str, note: Optional[str] = None) -> SlaCredit | None:
    """A month's measured uptime. Below the commitment: a service credit,
    expected on the next invoice (rule contract.sla_credit_auto_expect), and
    a breach event for that month. Returns the credit, or None if the SLA was met."""
    if ob.type != "sla_uptime":
        raise ObligationError("downtime is recorded on an SLA obligation")
    if ob.status not in ("open", "breached"):
        raise ObligationError("confirm the SLA obligation first")
    try:
        datetime.strptime(period, "%Y-%m")
    except ValueError:
        raise ObligationError("period looks like 2026-10")
    if not 0 <= measured_uptime_pct <= 100:
        raise ObligationError("uptime is a percentage between 0 and 100")
    existing = (await db.execute(select(SlaCredit).where(
        SlaCredit.obligation_id == ob.id, SlaCredit.period == period))).scalars().first()
    if existing:
        raise ObligationError(f"uptime for {period} is already recorded")
    contract = await db.get(Contract, ob.contract_id)
    fee, currency = await monthly_fee(db, contract)
    credit = ox.sla_credit(ob.value or {}, measured_uptime_pct, fee)
    details = {"period": period, "measured_uptime_pct": measured_uptime_pct, **credit, "note": note}
    _event(db, ob, "downtime_recorded", actor, details)
    row = None
    if credit["credit_amount"] > 0:
        auto = bool(get_rule("contract.sla_credit_auto_expect", fallback=True))
        row = SlaCredit(
            id=str(uuid.uuid4()), obligation_id=ob.id, contract_id=ob.contract_id,
            purchase_request_id=contract.purchase_request_id, period=period, measured_uptime_pct=measured_uptime_pct,
            credit_pct=credit["credit_pct"], credit_amount=credit["credit_amount"], currency=currency,
            status="expected" if auto else "proposed", recorded_by=actor, note=note, created_at=_now())
        db.add(row)
        _event(db, ob, "breach", actor, {"period": period, "source": "sla", "credit_amount": credit["credit_amount"]})
    # The month's review is done either way.
    if ob.due_date and ob.due_date <= _month_end(datetime.strptime(period, "%Y-%m").date()):
        ob.due_date = next_due(ob)
    ob.updated_at = _now()
    return row


async def resolve_credit(db: AsyncSession, credit: SlaCredit, status: str, actor: str, note: Optional[str] = None) -> SlaCredit:
    """expected (accept a proposed credit) | applied (seen on an invoice) | waived."""
    allowed = {"proposed": {"expected", "waived"}, "expected": {"applied", "waived"}}
    if status not in allowed.get(credit.status, set()):
        raise ObligationError(f"a {credit.status} credit can't become {status}")
    if status == "waived" and not (note or "").strip():
        raise ObligationError("say why the credit is waived")
    credit.status, credit.note = status, note or credit.note
    if status in ("applied", "waived"):
        credit.resolved_by, credit.resolved_at = actor, _now()
    await write_audit_log(db, "contract", credit.contract_id, f"sla_credit_{status}",
                          {"credit_id": credit.id, "period": credit.period, "amount": float(credit.credit_amount),
                           "by": actor, "note": note})
    return credit


# ── the sweep: reminders and licence limits ─────────────────────────────────

async def _already(db: AsyncSession, ob_id: str, key: str) -> bool:
    return (await db.execute(text(
        "SELECT 1 FROM obligation_events WHERE obligation_id = :o AND kind = 'reminder_sent' "
        "AND details->>'key' = :k LIMIT 1"), {"o": ob_id, "k": key})).first() is not None


def _payload(ob: ContractObligation, contract: Contract, kind: str, today: date, detail: str) -> dict:
    return {
        "obligation_id": ob.id, "contract_id": ob.contract_id, "vendor_id": contract.vendor_id,
        "type": ob.type, "label": ox.TYPES[ob.type].label, "kind": kind,
        "due_date": ob.due_date.isoformat() if ob.due_date else None,
        "days_left": (ob.due_date - today).days if ob.due_date else None,
        "owner_email": ob.owner_email, "detail": detail,
    }


def reminder_due(ob: ContractObligation, today: date, thresholds: list[int]) -> Optional[tuple[str, str, int]]:
    """(dedup key, detail, days_left) when a reminder is due today, else None.
    One reminder per threshold crossed (the nearest one, so a sweep that
    starts late doesn't send all of them at once), one on the day for the
    monthly SLA review, and one once it is overdue."""
    if ob.due_date is None:
        return None
    days_left = (ob.due_date - today).days
    if days_left < 0:
        return f"{ob.due_date}:overdue", f"overdue since {ob.due_date.isoformat()}", days_left
    if ob.recurrence == "monthly":
        # A monthly SLA review is due on the last day of the month.
        if days_left > 0:
            return None
        return f"{ob.due_date}:0", "record this month's uptime or mark the SLA met", days_left
    crossed = [d for d in thresholds if days_left <= d]
    if not crossed:
        return None
    return f"{ob.due_date}:{min(crossed)}", f"due in {days_left} days", days_left


async def sweep_reminders(session_factory, producer, today: Optional[date] = None) -> int:
    today = today or _now().date()
    thresholds = reminder_days()
    sent = 0
    async with session_factory() as db:
        rows = (await db.execute(
            select(ContractObligation, Contract).join(Contract, Contract.id == ContractObligation.contract_id)
            .where(ContractObligation.status.in_(["open", "breached"])))).all()
        outbox = staged(producer, db)
        for ob, contract in rows:
            # 1. Licence limit: more users than the contract allows.
            if ob.type == "license_limit" and ob.license_id and (ob.value or {}).get("seats"):
                lic = (await db.execute(text("SELECT app_name, assigned_seats FROM licenses WHERE id = :l"),
                                        {"l": ob.license_id})).first()
                if lic is not None:
                    cap, used = int(ob.value["seats"]), int(lic.assigned_seats or 0)
                    if used > cap and ob.status == "open":
                        ob.status = "breached"
                        _event(db, ob, "breach", "obligation-sweep", {"source": "licence", "assigned_seats": used, "seats": cap})
                        if outbox is not None:
                            await outbox.publish_obligation_due(_payload(
                                ob, contract, "breach", today, f"{lic.app_name}: {used} users assigned, contract allows {cap}"))
                        sent += 1
                    elif used <= cap and ob.status == "breached" and await _last_breach_was_licence(db, ob.id):
                        ob.status = "open"
                        _event(db, ob, "back_within", "obligation-sweep", {"assigned_seats": used, "seats": cap})
            # 2. Due-date reminders.
            if ob.status != "open":
                continue
            due = reminder_due(ob, today, thresholds)
            if due is None:
                continue
            key, detail, days_left = due
            if await _already(db, ob.id, key):
                continue
            _event(db, ob, "reminder_sent", "obligation-sweep", {"key": key, "days_left": days_left})
            if outbox is not None:
                await outbox.publish_obligation_due(_payload(
                    ob, contract, "overdue" if days_left < 0 else "due", today, detail))
            sent += 1
        await db.commit()
    if sent:
        logger.info(f"Obligation reminders / breaches published: {sent}")
    return sent


async def _last_breach_was_licence(db: AsyncSession, ob_id: str) -> bool:
    row = (await db.execute(text(
        "SELECT details->>'source' FROM obligation_events WHERE obligation_id = :o AND kind = 'breach' "
        "ORDER BY created_at DESC LIMIT 1"), {"o": ob_id})).first()
    return bool(row and row[0] == "licence")


async def run_obligation_sweeps(session_factory, producer):
    while True:
        try:
            await sweep_extraction(session_factory)
            await sweep_reminders(session_factory, producer)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"Obligation sweep failed: {e}", exc_info=True)
        await asyncio.sleep(SWEEP_SECONDS)
