"""Operations view of the event backbone: outbox backlog, dead-lettered
events, replay, the reconciler — plus showcase-only fault injection."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session_factory, get_db
from app.kafka.consumer import CONSUMER_NAME, dispatch
from app.kafka.events import build_event
from app.services import order_monitor
from shared.auth import CurrentUser, get_current_user, require_role
from shared.eventing import deliver, dlq_counts, list_dlq, outbox_stats, replay_dlq_entry, resolve_dlq_entry

router = APIRouter(dependencies=[Depends(require_role("finance", "admin"))])


@router.get("/eventing")
async def eventing_status(db: AsyncSession = Depends(get_db)):
    """Platform-wide: every service shares the outbox/DLQ tables."""
    return {"data": {
        "outbox": await outbox_stats(db), "dlq": await dlq_counts(db), "showcase_mode": settings.showcase_mode,
    }}


@router.get("/dlq")
async def get_dlq(status: str = "open", consumer: str | None = None, db: AsyncSession = Depends(get_db)):
    return {"data": await list_dlq(db, consumer=consumer, status=status)}


@router.post("/dlq/{dlq_id}/replay")
async def replay(dlq_id: str, user: CurrentUser = Depends(get_current_user)):
    try:
        result = await replay_dlq_entry(async_session_factory, dlq_id, CONSUMER_NAME, dispatch, user.email)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"data": result}


@router.post("/dlq/{dlq_id}/discard")
async def discard(dlq_id: str, reason: str = "discarded by operator", user: CurrentUser = Depends(get_current_user)):
    await resolve_dlq_entry(async_session_factory, dlq_id, "discarded", user.email, reason)
    return {"data": {"id": dlq_id, "status": "discarded"}}


@router.post("/reconcile")
async def reconcile(user: CurrentUser = Depends(get_current_user)):
    return {"data": await order_monitor.reconcile(performed_by=user.email)}


@router.post("/showcase/inject-out-of-order-event")
async def inject_out_of_order_event(request: Request, db: AsyncSession = Depends(get_db),
                                    user: CurrentUser = Depends(get_current_user)):
    """Showcase only: delivers an invoice.matched event for a request that
    is still awaiting approval — an event arriving in an impossible order.
    The lifecycle state machine refuses the transition and the consumer
    parks the event in the DLQ with the reason, instead of either
    corrupting the request or silently dropping the event."""
    if not settings.showcase_mode:
        raise HTTPException(status_code=404, detail="showcase mode is off")
    row = (
        await db.execute(text(
            "SELECT id FROM purchase_requests WHERE status = 'pending_approval' ORDER BY created_at DESC LIMIT 1"
        ))
    ).first()
    request_id = str(row.id) if row else str(uuid.uuid4())
    event = build_event("invoice.matched", "showcase", {
        "document_id": str(uuid.uuid4()), "invoice_number": "SHOWCASE-OUT-OF-ORDER",
        "purchase_request_id": request_id, "po_number": f"PO-{request_id[:8].upper()}",
        "vendor_id": None, "invoice_total": 1000.0, "po_total": 1000.0, "matched_at": None,
    })
    # Handed to this service's own consumer path (retry -> DLQ) rather than
    # published: invoice.matched belongs to document-vendor-agent, and the
    # broker's permissions (infra/redpanda/acls.conf) rightly refuse it from
    # this service.
    import asyncio
    asyncio.create_task(deliver(
        async_session_factory, CONSUMER_NAME, "invoice.matched", event,
        lambda: dispatch("invoice.matched", event),
    ))
    return {"data": {"event_id": event["event_id"], "purchase_request_id": request_id, "injected_by": user.email}}
