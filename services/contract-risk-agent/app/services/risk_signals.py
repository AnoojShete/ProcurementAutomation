"""Risk-model inputs from what the platform already knows (BR-7 / FR-30).

Two signals come from platform history, recomputed before every score:
  vendor_tenure_months    since the vendor's first record here (vendor row,
                          first document or first purchase request)
  on_time_delivery_rate   share of delivered orders received within
                          vendor.expected_delivery_days (rule, default 14)
                          of the contract being signed (the request going
                          to 'ordered'); None until one order is delivered

The compliance signals — security certification, breach disclosures,
high-risk geography, financial stability — have no platform source, so
finance records them (update_compliance_signals, audit-logged).
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text

from app.models import VendorRiskFeatures
from app.services.audit import write_audit_log

EXPECTED_DELIVERY_DAYS_FALLBACK = 14
COMPLIANCE_FIELDS = ("security_cert_flag", "geo_risk_flag", "breach_disclosure_count", "financial_stability_score")

_FIRST_SEEN = text("""
    SELECT LEAST(
        (SELECT created_at FROM vendors WHERE id = :vid),
        (SELECT MIN(created_at) FROM documents WHERE vendor_id = :vid),
        (SELECT MIN(created_at) FROM purchase_requests WHERE vendor_id = :vid))
""")

# One row per delivered order: contract signed (ordered) -> first
# "received" marker written by approval-inventory-agent (apply_received).
_DELIVERIES = text("""
    SELECT c.signed_at AS ordered_at, r.received_at
    FROM purchase_requests pr
    JOIN contracts c ON c.purchase_request_id = pr.id AND c.signed_at IS NOT NULL
    JOIN LATERAL (
        SELECT MIN(created_at) AS received_at FROM audit_log
        WHERE entity_id = pr.id AND action = 'contract_fulfilment_applied'
    ) r ON r.received_at IS NOT NULL
    WHERE pr.vendor_id = :vid
""")


def expected_delivery_days() -> int:
    from shared.rules_engine import get_rule
    return int(get_rule("vendor.expected_delivery_days", fallback=EXPECTED_DELIVERY_DAYS_FALLBACK))


def tenure_months(first_seen: Optional[datetime], now: datetime) -> Optional[int]:
    if first_seen is None:
        return None
    return max(0, (now.year - first_seen.year) * 12 + now.month - first_seen.month - (now.day < first_seen.day))


def on_time_rate(deliveries: list, allowed_days: int) -> tuple[Optional[float], int, int]:
    """(rate, on time, delivered) — rate None when nothing was delivered yet."""
    done = [(o, r) for o, r in deliveries if o and r]
    on_time = sum(1 for o, r in done if (r - o).total_seconds() <= allowed_days * 86400)
    return (round(on_time / len(done), 3) if done else None), on_time, len(done)


async def platform_signals(db, vendor_id: str, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    first_seen = (await db.execute(_FIRST_SEEN, {"vid": vendor_id})).scalar()
    rows = (await db.execute(_DELIVERIES, {"vid": vendor_id})).all()
    days = expected_delivery_days()
    rate, on_time, delivered = on_time_rate([(r.ordered_at, r.received_at) for r in rows], days)
    return {"vendor_tenure_months": tenure_months(first_seen, now), "on_time_delivery_rate": rate,
            "deliveries": delivered, "deliveries_on_time": on_time, "expected_delivery_days": days}


async def _features_row(db, vendor_id: str) -> VendorRiskFeatures:
    row = await db.get(VendorRiskFeatures, vendor_id)
    if row is None:
        row = VendorRiskFeatures(vendor_id=vendor_id, security_cert_flag=False, geo_risk_flag=False)
        db.add(row)
    return row


async def refresh_platform_signals(db, vendor_id: str) -> dict:
    """Writes the platform-derived signals onto the vendor's feature row
    (leaving finance's compliance fields alone). Caller commits."""
    signals = await platform_signals(db, vendor_id)
    row = await _features_row(db, vendor_id)
    row.vendor_tenure_months = signals["vendor_tenure_months"]
    row.on_time_delivery_rate = signals["on_time_delivery_rate"]
    row.updated_at = datetime.now(timezone.utc)
    return signals


async def update_compliance_signals(db, vendor_id: str, changes: dict, changed_by: str) -> dict:
    """Finance's compliance record for a vendor. Only the given fields
    change; before/after go to the audit log. Caller commits and re-scores."""
    row = await _features_row(db, vendor_id)
    before = {f: _plain(getattr(row, f, None)) for f in COMPLIANCE_FIELDS}
    for field, value in changes.items():
        if field in COMPLIANCE_FIELDS:
            setattr(row, field, value)
    row.updated_at = datetime.now(timezone.utc)
    after = {f: _plain(getattr(row, f, None)) for f in COMPLIANCE_FIELDS}
    await write_audit_log(db, "vendor", vendor_id, "risk_signals_updated",
                          {"changed_by": changed_by, "before": before, "after": after})
    return after


def _plain(v):
    return float(v) if v is not None and not isinstance(v, (bool, int, float)) else v
