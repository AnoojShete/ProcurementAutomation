"""Operational performance collectors: delivery_sla, feedback, incidents (Prompt 9B section 4).
Internal sources: provider='internal', body_text contains exact JSON list of records used.
"""
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Vendor
from app.services.collectors.base import record_observation, record_raw_response

logger = logging.getLogger(__name__)


async def collect_delivery_sla(
    db: AsyncSession, vendor: Vendor, now: datetime
) -> Tuple[Any, Any]:
    """Collects delivery SLA adherence from purchase requests and contracts.
    Signed -> goods_received (contract_fulfilment_applied). Excused orders excluded.
    """
    provider = "internal"

    from shared.rules_engine import get_rule
    allowed_days_default = int(get_rule("vendor.expected_delivery_days", fallback=14))

    # Query delivered orders: contract signed -> goods received
    delivered_query = text("""
        SELECT pr.id AS pr_id, c.id AS contract_id, c.signed_at, r.received_at, c.notice_period_days
        FROM purchase_requests pr
        JOIN contracts c ON c.purchase_request_id = pr.id AND c.signed_at IS NOT NULL
        JOIN LATERAL (
            SELECT MIN(created_at) AS received_at FROM audit_log
            WHERE entity_id = pr.id AND action IN ('contract_fulfilment_applied', 'goods_received')
        ) r ON r.received_at IS NOT NULL
        WHERE pr.vendor_id = :vid
          AND NOT EXISTS (
              SELECT 1 FROM audit_log al
              WHERE al.entity_id = pr.id AND al.action = 'order_delay_excused'
          )
    """)
    rows = (await db.execute(delivered_query, {"vid": vendor.id})).all()

    # Query excused orders
    excused_query = text("""
        SELECT pr.id AS pr_id, al.created_at, al.payload
        FROM purchase_requests pr
        JOIN audit_log al ON al.entity_id = pr.id AND al.action = 'order_delay_excused'
        WHERE pr.vendor_id = :vid
    """)
    excused_rows = (await db.execute(excused_query, {"vid": vendor.id})).all()
    excused_orders_list = [str(r.pr_id) for r in excused_rows]

    orders_delivered = len(rows)
    orders_on_time = 0
    records_used = []

    for r in rows:
        diff_seconds = (r.received_at - r.signed_at).total_seconds()
        is_on_time = diff_seconds <= (allowed_days_default * 86400)
        if is_on_time:
            orders_on_time += 1
        records_used.append({
            "purchase_request_id": str(r.pr_id),
            "contract_id": str(r.contract_id),
            "signed_at": r.signed_at.isoformat(),
            "received_at": r.received_at.isoformat(),
            "days_taken": round(diff_seconds / 86400, 1),
            "on_time": is_on_time,
        })

    on_time_pct = int(round((orders_on_time / orders_delivered) * 100)) if orders_delivered > 0 else 0

    fields = {
        "sla.orders_delivered": orders_delivered,
        "sla.orders_on_time": orders_on_time,
        "sla.on_time_pct": on_time_pct,
        "sla.allowed_days": allowed_days_default,
        "sla.excused_orders": len(excused_orders_list),
    }

    raw = await record_raw_response(
        db=db,
        vendor_id=vendor.id,
        signal_key="delivery_sla",
        provider=provider,
        request_method="INTERNAL",
        body={"records_used": records_used, "excused_orders": excused_orders_list},
        source_id="approval_inventory_orders",
        response_status=200,
        fetched_at=now,
    )

    facts = [
        {"label": "Source", "value": "Internal Order System"},
        {"label": "Retrieved", "value": now.strftime("%Y-%m-%d %H:%M:%S UTC")},
        {"label": "HTTP status", "value": "internal"},
        {"label": "Delivered orders", "value": str(orders_delivered)},
        {"label": "On-time deliveries", "value": f"{orders_on_time} ({on_time_pct}%)"},
        {"label": "Allowed SLA days", "value": str(allowed_days_default)},
        {"label": "Excused orders", "value": str(len(excused_orders_list))},
    ]

    obs_status = "ok" if orders_delivered >= 3 else "not_checked"
    obs = await record_observation(
        db=db,
        vendor_id=vendor.id,
        signal_key="delivery_sla",
        source_name="Delivery SLA Adherence",
        provider=provider,
        status=obs_status,
        facts=facts,
        fields=fields,
        raw_response_id=raw.id,
        record_refs=[r["purchase_request_id"] for r in records_used],
        ttl_days=1,
        fetched_at=now,
    )
    return obs, raw


async def collect_feedback(
    db: AsyncSession, vendor: Vendor, now: datetime
) -> Tuple[Any, Any]:
    """Collects feedback ratings from non-disputed reviews in last 12 months (plain mean)."""
    provider = "internal"
    one_year_ago = now - timedelta(days=365)

    # Query audit log for feedback submissions
    feedback_query = text("""
        SELECT al.id, al.created_at, al.payload
        FROM audit_log al
        WHERE al.entity_type = 'vendor_feedback'
          AND (al.payload->>'vendor_id') = :vid
          AND al.created_at >= :since
          AND NOT EXISTS (
              SELECT 1 FROM audit_log d
              WHERE d.entity_id = al.id AND d.action = 'vendor_feedback_disputed'
          )
        ORDER BY al.created_at DESC
    """)
    rows = (await db.execute(feedback_query, {"vid": vendor.id, "since": one_year_ago})).all()

    ratings = []
    dimensions = {}
    records_used = []

    for r in rows:
        payload = r.payload or {}
        score = payload.get("overall_rating") or payload.get("score")
        if score is not None:
            try:
                score_val = float(score)
                ratings.append(score_val)
                records_used.append({
                    "id": str(r.id),
                    "created_at": r.created_at.isoformat(),
                    "score": score_val,
                    "dimension": payload.get("dimension", "service_quality"),
                })
                dim = payload.get("dimension", "service_quality")
                dimensions.setdefault(dim, []).append(score_val)
            except (ValueError, TypeError):
                continue

    count_12m = len(ratings)
    mean_12m = round(sum(ratings) / count_12m, 1) if count_12m > 0 else 0.0
    min_rating = min(ratings) if count_12m > 0 else 0.0
    max_rating = max(ratings) if count_12m > 0 else 0.0

    lowest_dim = "service_quality"
    lowest_dim_mean = 0.0
    if dimensions:
        dim_averages = {k: sum(v) / len(v) for k, v in dimensions.items()}
        lowest_dim = min(dim_averages, key=dim_averages.get)
        lowest_dim_mean = round(dim_averages[lowest_dim], 1)

    fields = {
        "fbk.count_12m": count_12m,
        "fbk.mean_12m": mean_12m,
        "fbk.min": min_rating,
        "fbk.max": max_rating,
        "fbk.lowest_dimension": lowest_dim,
        "fbk.lowest_dimension_mean": lowest_dim_mean,
    }

    raw = await record_raw_response(
        db=db,
        vendor_id=vendor.id,
        signal_key="feedback",
        provider=provider,
        request_method="INTERNAL",
        body={"records_used": records_used},
        source_id="vendor_feedback_log",
        response_status=200,
        fetched_at=now,
    )

    facts = [
        {"label": "Source", "value": "Procurement Feedback System"},
        {"label": "Retrieved", "value": now.strftime("%Y-%m-%d %H:%M:%S UTC")},
        {"label": "HTTP status", "value": "internal"},
        {"label": "Ratings count (12m)", "value": str(count_12m)},
        {"label": "Mean rating", "value": f"{mean_12m}/5.0" if count_12m > 0 else "None"},
        {"label": "Lowest dimension", "value": f"{lowest_dim} ({lowest_dim_mean}/5.0)" if count_12m > 0 else "None"},
    ]

    obs_status = "ok" if count_12m >= 3 else "not_checked"
    obs = await record_observation(
        db=db,
        vendor_id=vendor.id,
        signal_key="feedback",
        source_name="Internal Procurement Feedback",
        provider=provider,
        status=obs_status,
        facts=facts,
        fields=fields,
        raw_response_id=raw.id,
        record_refs=[r["id"] for r in records_used],
        ttl_days=1,
        fetched_at=now,
    )
    return obs, raw


async def collect_incidents(
    db: AsyncSession, vendor: Vendor, now: datetime
) -> Tuple[Any, Any]:
    """Collects operational incidents in the last 24 months (Prompt 9C Section A)."""
    provider = "internal"
    two_years_ago = now - timedelta(days=730)

    from shared.rules_engine import get_rule
    min_rel_days = int(get_rule("risk.min_relationship_days", fallback=90))

    # Check relationship age
    created_at = getattr(vendor, "created_at", None)
    if not created_at:
        v_created = (await db.execute(text("SELECT created_at FROM vendors WHERE id = :id"), {"id": vendor.id})).scalar()
        created_at = v_created

    rel_age_days = (now - created_at).days if created_at else 0

    # Check delivered orders (>= 1 delivered order constitutes operational history)
    delivered_count_query = text("""
        SELECT COUNT(DISTINCT pr.id)
        FROM purchase_requests pr
        JOIN contracts c ON c.purchase_request_id = pr.id AND c.signed_at IS NOT NULL
        JOIN audit_log al ON al.entity_id = pr.id AND al.action IN ('contract_fulfilment_applied', 'goods_received')
        WHERE pr.vendor_id = :vid
    """)
    delivered_orders = (await db.execute(delivered_count_query, {"vid": vendor.id})).scalar() or 0

    # Query audit log or incident records
    incident_query = text("""
        SELECT al.id, al.created_at, al.payload
        FROM audit_log al
        WHERE al.entity_type = 'vendor_incident'
          AND (al.payload->>'vendor_id') = :vid
          AND al.created_at >= :since
        ORDER BY al.created_at DESC
    """)
    rows = (await db.execute(incident_query, {"vid": vendor.id, "since": two_years_ago})).all()

    count_24m = len(rows)
    # A recorded incident is itself a track record, whatever the relationship's age.
    history_available = (delivered_orders >= 1 or rel_age_days >= min_rel_days or count_24m > 0)
    latest_date = rows[0].created_at.strftime("%d %b %Y") if rows else "—"
    records_used = [{"id": str(r.id), "date": r.created_at.isoformat(), "payload": r.payload} for r in rows]

    fields = {
        "inc.history_available": history_available,
        "inc.count_24m": count_24m,
        "inc.latest_date": latest_date,
        "inc.delivered_orders": delivered_orders,
        "inc.relationship_days": rel_age_days,
    }

    raw = await record_raw_response(
        db=db,
        vendor_id=vendor.id,
        signal_key="incidents",
        provider=provider,
        request_method="INTERNAL",
        body={"records_used": records_used, "history_available": history_available},
        source_id="incident_log",
        response_status=200,
        fetched_at=now,
    )

    facts = [
        {"label": "Source", "value": "Internal Incident Log"},
        {"label": "Retrieved", "value": now.strftime("%Y-%m-%d %H:%M:%S UTC")},
        {"label": "HTTP status", "value": "internal"},
        {"label": "History available", "value": "Yes" if history_available else "No"},
        {"label": "Incident count (24m)", "value": str(count_24m)},
        {"label": "Latest incident", "value": latest_date},
    ]

    obs_status = "ok" if history_available else "not_checked"
    obs = await record_observation(
        db=db,
        vendor_id=vendor.id,
        signal_key="incidents",
        source_name="Operational Incidents",
        provider=provider,
        status=obs_status,
        facts=facts,
        fields=fields,
        raw_response_id=raw.id,
        record_refs=[r["id"] for r in records_used],
        ttl_days=1,
        fetched_at=now,
    )
    return obs, raw
