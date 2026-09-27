"""Order monitor — an autonomous agent that checks every open purchase
order on a fixed interval (order_monitor.interval_minutes in config.yaml,
60 by default) and writes a status summary: what's waiting on whom, what
is overdue, and what changed since the previous check.

Each run is stored in order_status_summaries and published as
order.summary.generated, so the assistant/chatbot and notifications can
answer "what's pending?" from the latest snapshot instead of querying
every service. GET /orders/summary/latest serves it over HTTP.

Buckets follow the purchase-request lifecycle:
  pending_approval -> approved -> fulfilled (contract signed, waiting on
  the vendor's delivery/invoice) -> invoice_received
plus backordered (is_backordered) and rejected.
"""
import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text

from app.config import load_config
from app.database import async_session_factory

logger = logging.getLogger(__name__)

LOCK_KEY = "order-monitor:run-lock"
MAX_ATTENTION_ITEMS = 25


@dataclass
class OrderRow:
    id: str
    status: str
    requested_by: str
    department: str
    amount: float
    currency: str
    vendor_name: Optional[str]
    is_backordered: bool
    sla_deadline: Optional[datetime]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    contract_status: Optional[str]


def monitor_config() -> dict:
    cfg = load_config().get("order_monitor", {}) or {}
    return {
        "interval_minutes": int(cfg.get("interval_minutes", 60)),
        "delivery_followup_days": int(cfg.get("delivery_followup_days", 14)),
        "signature_followup_days": int(cfg.get("signature_followup_days", 3)),
        "auto_repair": bool(cfg.get("auto_repair", True)),
    }


def _money(amount: float, currency: str) -> str:
    return f"{currency} {amount:,.0f}"


def _age_days(since: Optional[datetime], now: datetime) -> Optional[int]:
    return None if since is None else max(0, (now - since).days)


def _label(o: OrderRow) -> str:
    who = o.vendor_name or o.department
    return f"{who} request {o.id[:8]} ({_money(o.amount, o.currency)})"


def build_summary(orders: list[OrderRow], now: datetime, since: datetime, cfg: dict) -> dict:
    """Pure: turns order rows into the stored/published summary."""
    pending = [o for o in orders if o.status == "pending_approval"]
    overdue = [o for o in pending if o.sla_deadline and o.sla_deadline < now]
    # An approved request whose contract is already signed missed its
    # contract.signed -> fulfilled update. It is waiting on the vendor like
    # any fulfilled order, and flagged so someone can fix the record.
    out_of_sync = [o for o in orders if o.status == "approved" and o.contract_status == "signed"]
    awaiting_signature = [o for o in orders if o.status == "approved" and o.contract_status != "signed"]
    awaiting_delivery = [o for o in orders if o.status in ("fulfilled", "partially_invoiced")] + out_of_sync
    delivery_late_cutoff = now - timedelta(days=cfg["delivery_followup_days"])
    delivery_late = [o for o in awaiting_delivery if o.updated_at and o.updated_at < delivery_late_cutoff]
    backordered = [o for o in orders if o.is_backordered and o.status not in ("rejected", "invoice_received")]

    def changed(o: OrderRow) -> bool:
        return bool(o.updated_at and o.updated_at >= since)

    new_requests = [o for o in orders if o.created_at and o.created_at >= since]
    completed = [o for o in orders if o.status == "invoice_received" and changed(o)]
    rejected = [o for o in orders if o.status == "rejected" and changed(o)]
    approved_recently = [o for o in orders if o.status in ("approved", "fulfilled") and changed(o)]

    attention: list[dict] = []
    for o in sorted(overdue, key=lambda o: o.sla_deadline):
        hours = int((now - o.sla_deadline).total_seconds() // 3600)
        attention.append({
            "request_id": o.id, "kind": "approval_overdue", "severity": "high",
            "message": f"{_label(o)} is {hours}h past its approval SLA",
        })
    signature_cutoff = now - timedelta(days=cfg["signature_followup_days"])
    contract_state = {
        None: "no contract generated yet",
        "draft": "contract not yet sent for signature",
        "pending_signature": "contract still awaiting signature",
    }
    stalled = [o for o in awaiting_signature if o.updated_at and o.updated_at < signature_cutoff]
    for o in sorted(stalled, key=lambda o: o.updated_at):
        attention.append({
            "request_id": o.id, "kind": "signature_stalled", "severity": "medium",
            "message": (
                f"{_label(o)} approved {_age_days(o.updated_at, now)} days ago; "
                f"{contract_state.get(o.contract_status, 'contract ' + str(o.contract_status).replace('_', ' '))}"
            ),
        })
    for o in sorted(delivery_late, key=lambda o: o.updated_at):
        attention.append({
            "request_id": o.id, "kind": "delivery_overdue", "severity": "medium",
            "message": f"{_label(o)} has waited {_age_days(o.updated_at, now)} days for vendor delivery/invoice",
        })
    for o in out_of_sync:
        attention.append({
            "request_id": o.id, "kind": "status_mismatch", "severity": "low",
            "message": f"{_label(o)} has a signed contract but is still marked approved",
        })
    for o in backordered:
        attention.append({
            "request_id": o.id, "kind": "backordered", "severity": "low",
            "message": f"{_label(o)} is backordered",
        })

    counts = {
        "pending_approval": len(pending),
        "approval_overdue": len(overdue),
        "awaiting_signature": len(awaiting_signature),
        "awaiting_delivery": len(awaiting_delivery),
        "delivery_overdue": len(delivery_late),
        "backordered": len(backordered),
    }
    changes = {
        "new_requests": len(new_requests),
        "approved": len(approved_recently),
        "invoices_received": len(completed),
        "rejected": len(rejected),
    }
    open_value = sum(o.amount for o in pending + awaiting_signature + awaiting_delivery)

    def plural(n: int, word: str) -> str:
        return f"{n} {word}{'' if n == 1 else 's'}"

    lines = [
        f"Order status as of {now.strftime('%d %b %Y, %H:%M UTC')}.",
        (
            f"{plural(len(pending), 'request')} awaiting approval"
            + (f" ({len(overdue)} past SLA)" if overdue else "")
            + f", {len(awaiting_signature)} approved and awaiting contract signature,"
            + f" {len(awaiting_delivery)} awaiting vendor delivery/invoice"
            + (f" ({len(delivery_late)} over {cfg['delivery_followup_days']} days)" if delivery_late else "")
            + (f", {len(backordered)} backordered" if backordered else "")
            + "."
        ),
        (
            f"Since {since.strftime('%H:%M UTC')}: {plural(changes['new_requests'], 'new request')}, "
            f"{changes['approved']} approved, {plural(changes['invoices_received'], 'invoice')} received, "
            f"{changes['rejected']} rejected."
        ),
    ]
    if attention:
        lines.append("Needs attention: " + "; ".join(a["message"] for a in attention[:5]) + ".")
    else:
        lines.append("Nothing needs attention.")

    return {
        "generated_at": now.isoformat(),
        "window_start": since.isoformat(),
        "counts": counts,
        "changes": changes,
        "open_order_value": round(open_value, 2),
        "attention": attention[:MAX_ATTENTION_ITEMS],
        "summary_text": " ".join(lines),
    }


async def _load_orders(db) -> list[OrderRow]:
    """Open orders plus anything that closed recently (for the
    since-last-check counts). Contracts belong to contract-risk-agent, so
    their status is read with a plain join rather than an ORM mapping."""
    rows = (
        await db.execute(text("""
            SELECT pr.id, pr.status, pr.requested_by, pr.department, pr.amount, pr.currency,
                   v.name AS vendor_name, COALESCE(pr.is_backordered, false) AS is_backordered,
                   pr.sla_deadline, pr.created_at, COALESCE(pr.updated_at, pr.created_at) AS updated_at,
                   (SELECT c.status FROM contracts c WHERE c.purchase_request_id = pr.id
                     ORDER BY c.generated_at DESC NULLS LAST LIMIT 1) AS contract_status
            FROM purchase_requests pr
            LEFT JOIN vendors v ON v.id = pr.vendor_id
            WHERE pr.status IN ('pending_approval', 'approved', 'fulfilled', 'partially_invoiced', 'backordered')
               OR COALESCE(pr.is_backordered, false)
               OR COALESCE(pr.updated_at, pr.created_at) >= now() - interval '7 days'
        """))
    ).all()
    return [
        OrderRow(
            id=str(r.id), status=r.status, requested_by=r.requested_by, department=r.department,
            amount=float(r.amount or 0), currency=r.currency or "INR", vendor_name=r.vendor_name,
            is_backordered=bool(r.is_backordered), sla_deadline=r.sla_deadline,
            created_at=r.created_at, updated_at=r.updated_at, contract_status=r.contract_status,
        )
        for r in rows
    ]


async def _previous_run_at(db) -> Optional[datetime]:
    return (await db.execute(text("SELECT max(generated_at) FROM order_status_summaries"))).scalar()


async def reconcile(performed_by: str = "order-monitor") -> list[dict]:
    """Repairs transitions that were lost before the outbox existed: a
    request still `approved` although its contract is signed gets the
    same effect a delivered contract.signed would have had (via the Kafka
    handler's own apply_contract_signed). Each repair is audited."""
    from app.kafka.consumer import apply_contract_signed
    from app.models import AuditLog

    async with async_session_factory() as db:
        rows = (
            await db.execute(text("""
                SELECT pr.id AS request_id, c.id AS contract_id
                FROM purchase_requests pr
                JOIN LATERAL (
                    SELECT id, status FROM contracts WHERE purchase_request_id = pr.id
                    ORDER BY signed_at DESC NULLS LAST, generated_at DESC NULLS LAST LIMIT 1
                ) c ON true
                WHERE pr.status = 'approved' AND c.status = 'signed'
            """))
        ).all()
    repaired = []
    for r in rows:
        async with async_session_factory() as db:
            try:
                outcome = await apply_contract_signed(db, str(r.contract_id), source="reconciler")
                db.add(AuditLog(
                    id=str(uuid.uuid4()), entity_type="purchase_request", entity_id=str(r.request_id),
                    action="reconciled_contract_signed", performed_by=performed_by,
                    created_at=datetime.now(timezone.utc),
                    details={"contract_id": str(r.contract_id), "outcome": outcome},
                ))
                await db.commit()
                repaired.append({"request_id": str(r.request_id), "contract_id": str(r.contract_id), "outcome": outcome})
            except Exception as e:
                await db.rollback()
                logger.warning(f"[order_monitor] could not reconcile request {r.request_id}: {e}")
                repaired.append({"request_id": str(r.request_id), "contract_id": str(r.contract_id), "outcome": f"failed: {e}"})
    # Second repair: the invoice ledger says a request is fully invoiced
    # but its status never caught up (its invoice.matched was lost).
    from app.models import PurchaseRequest
    async with async_session_factory() as db:
        rows = (
            await db.execute(text("""
                SELECT pr.id FROM purchase_requests pr
                JOIN (SELECT purchase_request_id, sum(amount) AS invoiced FROM invoice_allocations
                      GROUP BY purchase_request_id) a ON a.purchase_request_id = pr.id
                WHERE pr.status IN ('approved', 'fulfilled', 'partially_invoiced')
                  AND a.invoiced >= pr.amount * 0.99
            """))
        ).all()
    for r in rows:
        async with async_session_factory() as db:
            req = await db.get(PurchaseRequest, r.id)
            previous = req.status
            req.status = "invoice_received"
            req.updated_at = datetime.now(timezone.utc)
            db.add(AuditLog(
                id=str(uuid.uuid4()), entity_type="purchase_request", entity_id=str(r.id),
                action="reconciled_invoice_ledger", performed_by=performed_by, created_at=datetime.now(timezone.utc),
                details={"from": previous, "to": "invoice_received"},
            ))
            await db.commit()
            repaired.append({"request_id": str(r.id), "contract_id": "", "outcome": f"{previous} -> invoice_received (ledger)"})

    if repaired:
        logger.info(f"[order_monitor] reconciled {len(repaired)} request(s)")
    return repaired


async def run_once(kafka_producer=None, trigger: str = "scheduled") -> dict:
    cfg = monitor_config()
    repaired = await reconcile() if cfg["auto_repair"] else []
    now = datetime.now(timezone.utc)
    async with async_session_factory() as db:
        previous = await _previous_run_at(db)
        since = previous or now - timedelta(minutes=cfg["interval_minutes"])
        summary = build_summary(await _load_orders(db), now, since, cfg)
        summary_id = str(uuid.uuid4())
        await db.execute(
            text("""
                INSERT INTO order_status_summaries
                    (id, generated_at, window_start, trigger, counts, changes, attention, open_order_value, summary_text)
                VALUES (:id, :generated_at, :window_start, :trigger,
                        CAST(:counts AS JSONB), CAST(:changes AS JSONB), CAST(:attention AS JSONB),
                        :open_order_value, :summary_text)
            """),
            {
                "id": summary_id, "generated_at": now, "window_start": since, "trigger": trigger,
                "counts": _json(summary["counts"]), "changes": _json(summary["changes"]),
                "attention": _json(summary["attention"]), "open_order_value": summary["open_order_value"],
                "summary_text": summary["summary_text"],
            },
        )
        await db.commit()
    summary["id"] = summary_id
    summary["trigger"] = trigger
    summary["repaired"] = repaired
    logger.info(f"[order_monitor] {summary['summary_text']}")

    if kafka_producer is not None:
        try:
            await kafka_producer.publish_order_summary_generated(summary)
        except Exception as e:
            # The snapshot is already stored and served over HTTP; a Kafka
            # outage only delays push consumers until the next run.
            logger.warning(f"[order_monitor] could not publish order.summary.generated: {e}")
    return summary


def _json(value) -> str:
    import json
    return json.dumps(value, default=str)


async def run_order_monitor(kafka_producer, redis_client=None):
    """Background loop. With several API replicas, a Redis lock lets only
    one of them run each interval."""
    interval = monitor_config()["interval_minutes"] * 60
    # Give the rest of the stack (and this service's own migrations) a
    # moment before the first check.
    await asyncio.sleep(30)
    while True:
        try:
            acquired = True
            if redis_client is not None:
                acquired = bool(await redis_client.set(LOCK_KEY, "1", nx=True, ex=max(60, interval - 30)))
            if acquired:
                await run_once(kafka_producer)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"[order_monitor] run failed: {e}", exc_info=True)
        await asyncio.sleep(interval)
