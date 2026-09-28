"""Order monitor snapshots — see app/services/order_monitor.py. The
assistant/chatbot reads GET /orders/summary/latest to answer questions
about pending approvals, signatures and vendor deliveries."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services import order_monitor
from shared.auth import require_role

# Summaries list requests, vendors and amounts across the organisation —
# staff, and service callers (the assistant), only.
router = APIRouter(dependencies=[Depends(require_role("service", "approver", "finance", "admin"))])

_COLUMNS = "id, generated_at, window_start, trigger, counts, changes, attention, open_order_value, summary_text"


def _serialize(row) -> dict:
    return {
        "id": str(row.id),
        "generated_at": row.generated_at.isoformat(),
        "window_start": row.window_start.isoformat(),
        "trigger": row.trigger,
        "counts": row.counts,
        "changes": row.changes,
        "attention": row.attention,
        "open_order_value": float(row.open_order_value) if row.open_order_value is not None else None,
        "summary_text": row.summary_text,
    }


@router.get("/summary/latest")
async def latest_summary(db: AsyncSession = Depends(get_db)):
    row = (
        await db.execute(text(f"SELECT {_COLUMNS} FROM order_status_summaries ORDER BY generated_at DESC LIMIT 1"))
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="no order summary yet — the monitor runs shortly after startup")
    return {"data": _serialize(row), "meta": {"interval_minutes": order_monitor.monitor_config()["interval_minutes"]}}


@router.get("/summary")
async def summary_history(limit: int = 24, db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            text(f"SELECT {_COLUMNS} FROM order_status_summaries ORDER BY generated_at DESC LIMIT :limit"),
            {"limit": max(1, min(limit, 200))},
        )
    ).all()
    return {"data": [_serialize(r) for r in rows], "meta": {"count": len(rows)}}


@router.post("/summary/run", dependencies=[Depends(require_role("approver", "finance", "admin"))])
async def run_now(request: Request):
    """Run a check immediately instead of waiting for the next interval."""
    summary = await order_monitor.run_once(request.app.state.kafka_producer, trigger="manual")
    return {"data": summary}
