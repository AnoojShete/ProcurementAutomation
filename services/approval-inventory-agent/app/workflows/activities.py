"""
Temporal activities for the Approval Workflow.

Activities perform side effects (DB writes, Kafka publishes, Redis operations)
and are automatically retried by Temporal on failure. Each activity creates
its own connections since they run in the worker process context, not in
the FastAPI request context.
"""
import uuid
import json
import logging
from datetime import datetime, timezone
from typing import Optional
from temporalio import activity
from dataclasses import dataclass
from sqlalchemy import select

from app.database import async_session_factory
from app.models import PurchaseRequest, ApprovalHistory, AuditLog, Inventory
from app.config import settings, load_config
from app.models import PurchaseRequest, ApprovalHistory, AuditLog
from app.config import settings
from app.metrics import approval_escalated_total
from app.kafka.producer import KafkaEventProducer
from app.services.redis_lock import InventoryLock
from app.services.inventory_service import release_reservation
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


@dataclass
class ApprovalActivityInput:
    """Input for activities that need request + approver context."""
    request_id: str
    approver_id: str
    decision_level: str


@dataclass
class NotificationInput:
    """Input for the notification publishing activity."""
    recipient: str
    channel: str
    template_name: str
    template_context: dict
    priority: str
    related_entity_id: str


@activity.defn
async def fetch_request_details(request_id: str) -> dict:
    """Fetch purchase request details from the database.
    
    Creates a fresh DB session since activities run in the Temporal
    worker process, not in a FastAPI request context.
    """
    async with async_session_factory() as session:
        stmt = select(PurchaseRequest).where(PurchaseRequest.id == request_id)
        result = await session.execute(stmt)
        req = result.scalar_one_or_none()
        if not req:
            raise ValueError(f"Request {request_id} not found")

        # GAP-A5: read SLA from config.yaml, never hardcode
        config = load_config()
        sla_hours = config.get("sla", {}).get("approval_timeout_hours", 48)

        return {
            "id": req.id,
            "approval_chain": req.approval_chain or [],
            "sla_hours": sla_hours,
            "request_type": req.request_type,
            "items": req.items,
        }


@activity.defn
async def update_request_status(request_id: str, status: str, approver_index: int) -> None:
    """Update the request's status and current approver index in the database."""
    async with async_session_factory() as session:
        stmt = select(PurchaseRequest).where(PurchaseRequest.id == request_id)
        result = await session.execute(stmt)
        req = result.scalar_one_or_none()
        if req:
            req.status = status
            req.current_approver_index = approver_index
            req.updated_at = datetime.now(timezone.utc)
            await session.commit()
            logger.info(f"Request {request_id} updated: status={status}, index={approver_index}")


@activity.defn
async def record_approval_decision(
    request_id: str, decision: str, decided_by: str,
    decision_level: str, escalated: bool, comments: Optional[str] = None
) -> None:
    """Record an approval/rejection decision in the approval_history table.
    
    Also creates an audit log entry for the decision.
    """
    async with async_session_factory() as session:
        now = datetime.now(timezone.utc)

        # Record in approval_history (uses 'request_id' column, matching init.sql)
        history = ApprovalHistory(
            id=str(uuid.uuid4()),
            request_id=request_id,
            decision=decision,
            decided_by=decided_by,
            decision_level=decision_level,
            escalated=escalated,
            comments=comments,
            decided_at=now,
        )
        session.add(history)

        # Audit log (uses 'performed_by' and 'details', matching init.sql)
        audit = AuditLog(
            id=str(uuid.uuid4()),
            entity_type="purchase_request",
            entity_id=request_id,
            action=f"approval_{decision}",
            performed_by=decided_by,
            details={
                "decision": decision,
                "level": decision_level,
                "escalated": escalated,
            },
        )
        session.add(audit)

        await session.commit()
        if escalated:
            approval_escalated_total.inc()
        logger.info(
            f"Recorded {decision} for request {request_id} "
            f"by {decided_by} at level {decision_level}"
        )


@activity.defn
async def publish_approval_decided_event(
    request_id: str, decision: str, decided_by: str,
    decision_level: str, escalated: bool, comments: Optional[str] = None
) -> None:
    """Publish an approval.decided event to Kafka.
    
    Creates a fresh Kafka producer since activities run in the worker context.
    """
    producer = KafkaEventProducer(settings.kafka_bootstrap_servers)
    await producer.start()
    try:
        await producer.publish_approval_decided(
            request_id=request_id,
            decision=decision,
            decided_by=decided_by,
            decision_level=decision_level,
            escalated=escalated,
            comments=comments,
            decided_at=datetime.now(timezone.utc),
        )
    finally:
        await producer.stop()


@activity.defn
async def publish_notification_event(notification: NotificationInput) -> None:
    """Publish a notification.send event to Kafka for the notification agent."""
    producer = KafkaEventProducer(settings.kafka_bootstrap_servers)
    await producer.start()
    try:
        await producer.publish_notification(
            recipient=notification.recipient,
            channel=notification.channel,
            template_name=notification.template_name,
            template_context=notification.template_context,
            priority=notification.priority,
            related_entity_id=notification.related_entity_id,
        )
    finally:
        await producer.stop()


@activity.defn
async def release_inventory_lock(sku: str, request_id: str) -> None:
    """Release the Redis inventory lock for a given SKU.
    
    NOTE: The short-lived Redis lock used by reserve_stock() is already
    released inside reserve_stock() itself (in the `finally` block).
    This activity is kept for backward compatibility but is effectively a
    no-op at runtime — inventory de-reservation is handled by
    release_hardware_reservations() below.
    """
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        lock = InventoryLock(redis_client)
        released = await lock.release(sku, request_id)
        if released:
            logger.info(f"Released inventory lock for SKU {sku} (request {request_id})")
        else:
            logger.debug(
                f"Lock for SKU {sku} already released or expired (request {request_id})"
            )
    finally:
        await redis_client.aclose()


@activity.defn
async def release_hardware_reservations(request_id: str) -> None:
    """De-reserve all inventory stock held by a rejected/expired purchase request.

    GAP-A3 fix: previously release_reservation() was never called anywhere,
    leaving reserved_quantity permanently inflated after a rejection.

    This activity:
    1. Loads the purchase request and its items list.
    2. For each item with a SKU, calls release_reservation() which atomically
       decrements reserved_quantity and increments available_quantity.
    3. Non-hardware request types (license/saas/reclaim) are silently skipped
       since they don't reserve physical inventory.
    """
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        async with async_session_factory() as session:
            stmt = select(PurchaseRequest).where(PurchaseRequest.id == request_id)
            result = await session.execute(stmt)
            req = result.scalar_one_or_none()

            if not req or req.request_type != "hardware":
                return  # Only hardware requests hold physical reservations

            items = req.items or []
            for item in items:
                sku = item.get("sku")
                qty = item.get("quantity", 0)
                if sku and qty > 0:
                    released = await release_reservation(
                        session, redis_client, sku, request_id, qty
                    )
                    if released:
                        logger.info(
                            f"Released {qty}x {sku} reserved by request {request_id}"
                        )
                    else:
                        logger.warning(
                            f"Could not release {qty}x {sku} for request {request_id} "
                            f"(may have already been released)"
                        )
    finally:
        await redis_client.aclose()

@activity.defn
async def set_reclaim_cooldown(request_id: str) -> None:
    """Set reclaim_cooldown_until on the license when a reinstate request is approved."""
    from app.models import License
    from datetime import timedelta
    async with async_session_factory() as session:
        stmt = select(PurchaseRequest).where(PurchaseRequest.id == request_id)
        result = await session.execute(stmt)
        req = result.scalar_one_or_none()
        
        if not req or req.request_type != "reinstate":
            return
            
        items = req.items or []
        for item in items:
            license_id = item.get("license_id")
            if license_id:
                stmt_lic = select(License).where(License.id == license_id)
                res_lic = await session.execute(stmt_lic)
                lic = res_lic.scalar_one_or_none()
                if lic:
                    lic.reclaim_cooldown_until = datetime.now(timezone.utc) + timedelta(days=45)
        await session.commit()
