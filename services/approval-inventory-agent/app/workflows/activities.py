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
from temporalio import activity
from dataclasses import dataclass
from sqlalchemy import select

from app.database import async_session_factory
from app.models import PurchaseRequest, ApprovalHistory, AuditLog
from app.config import settings
from app.kafka.producer import KafkaEventProducer
from app.services.redis_lock import InventoryLock
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

        return {
            "id": req.id,
            "approval_chain": req.approval_chain or [],
            "sla_hours": 48,  # Could also be read from config
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
    decision_level: str, escalated: bool, comments: str = None
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
        logger.info(
            f"Recorded {decision} for request {request_id} "
            f"by {decided_by} at level {decision_level}"
        )


@activity.defn
async def publish_approval_decided_event(
    request_id: str, decision: str, decided_by: str,
    decision_level: str, escalated: bool, comments: str = None
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
    
    Called when a request is fully approved or rejected to free
    the reserved inventory for other requests.
    """
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        lock = InventoryLock(redis_client)
        released = await lock.release(sku, request_id)
        if released:
            logger.info(f"Released inventory lock for SKU {sku} (request {request_id})")
        else:
            logger.warning(
                f"Could not release lock for SKU {sku} — "
                f"may have expired or been released already"
            )
    finally:
        await redis_client.aclose()
