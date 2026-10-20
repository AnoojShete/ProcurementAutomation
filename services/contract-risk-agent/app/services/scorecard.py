"""Vendor scorecards (feature expansion Phase 3c).

How a vendor has actually performed, from data the platform already has:

  on_time_rate       deliveries received within vendor.expected_delivery_days
                     of contract signature (risk_signals.platform_signals)
  invoice_accuracy   share of the vendor's invoices that matched their
                     purchase request without a variance (invoice_matches)
  rfq_response_rate  share of RFQ invitations answered, counting only
                     rounds whose deadline has passed (rfq_invitations)
  sla_breaches       months with an SLA service credit (obligation_events, Phase 2)
  risk_band          the latest risk score

Stored in vendor_scorecards: recomputed for every active vendor once a day
and for one vendor whenever its page asks. RFQ scoring in
approval-inventory-agent reads on_time_rate from that table.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text

from app.services.risk_signals import platform_signals

logger = logging.getLogger(__name__)
DAY_SECONDS = 24 * 3600


async def _scalar_or_none(db, sql: str, params: dict):
    """Reads another service's table; None when it isn't there yet."""
    try:
        async with db.begin_nested():
            return (await db.execute(text(sql), params)).first()
    except Exception:
        return None


async def compute(db, vendor_id: str, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    signals = await platform_signals(db, vendor_id, now)
    inv = await _scalar_or_none(db, (
        "SELECT count(*) FILTER (WHERE status IN ('matched', 'partial')) AS clean, "
        "count(*) FILTER (WHERE status IN ('matched', 'partial', 'variance')) AS total "
        "FROM invoice_matches WHERE vendor_id = :v"), {"v": vendor_id})
    rfq = await _scalar_or_none(db, (
        "SELECT count(*) FILTER (WHERE i.responded_at IS NOT NULL) AS answered, count(*) AS total "
        "FROM rfq_invitations i JOIN rfq_events e ON e.id = i.rfq_id "
        "WHERE i.vendor_id = :v AND (i.round < e.round OR e.deadline < now() OR e.status <> 'open')"), {"v": vendor_id})
    sla = await _scalar_or_none(db, (
        "SELECT count(*) FROM obligation_events ev JOIN contract_obligations o ON o.id = ev.obligation_id "
        "JOIN contracts c ON c.id = o.contract_id "
        "WHERE c.vendor_id = :v AND ev.kind = 'breach' AND ev.details->>'source' = 'sla'"), {"v": vendor_id})
    band = await _scalar_or_none(db, "SELECT band FROM risk_scores WHERE vendor_id = :v "
                                     "ORDER BY scored_at DESC NULLS LAST LIMIT 1", {"v": vendor_id})
    invoices = int(inv.total) if inv else 0
    invited = int(rfq.total) if rfq else 0
    return {
        "vendor_id": str(vendor_id),
        "on_time_rate": signals["on_time_delivery_rate"], "deliveries": signals["deliveries"],
        "deliveries_on_time": signals["deliveries_on_time"], "expected_delivery_days": signals["expected_delivery_days"],
        "invoice_accuracy": round(int(inv.clean) / invoices, 3) if invoices else None, "invoices": invoices,
        "rfq_response_rate": round(int(rfq.answered) / invited, 3) if invited else None, "rfq_invitations": invited,
        "sla_breaches": int(sla[0]) if sla else 0,
        "risk_band": band[0] if band else None,
        "computed_at": now.isoformat(),
    }


async def refresh(db, vendor_id: str) -> dict:
    """Computes and stores one vendor's scorecard. Caller commits."""
    card = await compute(db, vendor_id)
    await db.execute(text(
        "INSERT INTO vendor_scorecards (vendor_id, on_time_rate, deliveries, invoice_accuracy, invoices, "
        "rfq_response_rate, rfq_invitations, sla_breaches, risk_band, computed_at) VALUES (:vendor_id, :on_time_rate, "
        ":deliveries, :invoice_accuracy, :invoices, :rfq_response_rate, :rfq_invitations, :sla_breaches, :risk_band, now()) "
        "ON CONFLICT (vendor_id) DO UPDATE SET on_time_rate = EXCLUDED.on_time_rate, deliveries = EXCLUDED.deliveries, "
        "invoice_accuracy = EXCLUDED.invoice_accuracy, invoices = EXCLUDED.invoices, "
        "rfq_response_rate = EXCLUDED.rfq_response_rate, rfq_invitations = EXCLUDED.rfq_invitations, "
        "sla_breaches = EXCLUDED.sla_breaches, risk_band = EXCLUDED.risk_band, computed_at = now()"),
        {k: card[k] for k in ("vendor_id", "on_time_rate", "deliveries", "invoice_accuracy", "invoices",
                              "rfq_response_rate", "rfq_invitations", "sla_breaches", "risk_band")})
    return card


async def refresh_all(session_factory) -> int:
    async with session_factory() as db:
        ids = [str(v) for (v,) in (await db.execute(text(
            "SELECT id FROM vendors WHERE COALESCE(status, 'active') <> 'offboarded'"))).all()]
        for vid in ids:
            await refresh(db, vid)
        await db.commit()
    logger.info(f"Vendor scorecards refreshed: {len(ids)}")
    return len(ids)


async def run_nightly(session_factory):
    await asyncio.sleep(120)  # let the stack settle after a start
    while True:
        try:
            await refresh_all(session_factory)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"Scorecard refresh failed: {e}", exc_info=True)
        await asyncio.sleep(DAY_SECONDS)
