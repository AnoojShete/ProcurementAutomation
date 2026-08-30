"""
Core approval business logic for the Approval & Inventory Intelligence Agent.

Handles:
- Spend-tier determination from configurable rules (config.yaml)
- Purchase request creation with inventory checks
- Approval/rejection decision processing
- Temporal workflow orchestration
- Kafka event publishing
"""
import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import load_spend_tiers, load_config, settings
from app.models import PurchaseRequest, ApprovalHistory, AuditLog, Inventory
from app.schemas import CreatePurchaseRequest, ApprovalAction
from app.kafka.producer import KafkaEventProducer
from app.services.inventory_service import check_availability, reserve_stock, split_backorder
from app.metrics import inventory_reservation_total


class ApprovalService:
    """Service handling all approval workflow logic.
    
    Instantiated per-request with the current DB session, Kafka producer,
    and Redis client injected via FastAPI dependency injection.
    """

    def __init__(self, db: AsyncSession, producer: KafkaEventProducer, redis_client):
        self.db = db
        self.producer = producer
        self.redis = redis_client

    def determine_spend_tier(self, amount: float) -> tuple[str, list[str]]:
        """Determine approval tier and chain from amount using config.yaml rules.
        
        Returns:
            Tuple of (tier_name, approval_chain) where tier_name is one of
            'auto', 'manager', 'manager+finance' and approval_chain is
            the ordered list of approver role IDs.
        """
        return ApprovalService.determine_spend_tier_static(amount)

    @staticmethod
    def determine_spend_tier_static(amount: float) -> tuple[str, list[str]]:
        """Static version of determine_spend_tier for use without instantiation.
        
        This is used by tests to verify tier routing without needing
        DB/Kafka/Redis dependencies.
        
        Rules (from config.yaml):
            - Up to ₹500:   auto-approved, no approval chain
            - ₹500-₹5,000:  manager approval
            - Above ₹5,000: manager + finance approval
        """
        tiers = load_spend_tiers()
        for tier in tiers:
            if tier["max_amount"] is None or amount <= tier["max_amount"]:
                return tier["name"], list(tier["approval_chain"])
        # Fallback to highest tier
        return tiers[-1]["name"], list(tiers[-1]["approval_chain"])

    async def list_requests(self, limit: int = 100) -> list[PurchaseRequest]:
        """Every purchase request, most recently created first — backs the
        tracking dashboard."""
        stmt = (
            select(PurchaseRequest)
            .options(selectinload(PurchaseRequest.approval_history))
            .order_by(PurchaseRequest.created_at.desc().nulls_last())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_request_with_history(self, request_id: str) -> PurchaseRequest:
        """Fetch a purchase request with its full approval history."""
        stmt = (
            select(PurchaseRequest)
            .options(selectinload(PurchaseRequest.approval_history))
            .where(PurchaseRequest.id == request_id)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_request(self, data: CreatePurchaseRequest) -> PurchaseRequest:
        """Create a new purchase request with proper tier routing.
        
        Flow:
        1. Determine spend tier from amount
        2. Calculate SLA deadline
        3. If hardware, check inventory and reserve stock
        4. Insert into purchase_requests table
        5. Publish approval.requested Kafka event
        6. If auto-approved (tier=auto), immediately approve
        7. Otherwise, start Temporal approval workflow
        """
        # 1. Determine spend tier
        tier_name, approval_chain = self.determine_spend_tier(data.amount)

        # 2. Calculate SLA deadline
        config = load_config()
        sla_hours = config.get("sla", {}).get("approval_timeout_hours", 48)
        sla_deadline = datetime.now(timezone.utc) + timedelta(hours=sla_hours)

        req_id = str(uuid.uuid4())
        is_backordered = False

        # 3. If hardware, check inventory and reserve stock
        total_available = 0
        if data.request_type == "hardware" and data.items:
            for item in data.items:
                sku = item.get("sku")
                qty = item.get("quantity", 1)
                if sku:
                    stmt = select(Inventory).where(Inventory.sku == sku)
                    result = await self.db.execute(stmt)
                    inv_item = result.scalar_one_or_none()
                    item_avail = inv_item.available_quantity if inv_item else 0
                    
                    if item_avail >= qty:
                        reserved = await reserve_stock(
                            self.db, self.redis, sku, req_id, qty
                        )
                        if reserved:
                            total_available += qty
                            inventory_reservation_total.labels(status="reserved").inc()
                        else:
                            is_backordered = True
                            total_available += item_avail
                            inventory_reservation_total.labels(status="backordered").inc()
                    else:
                        is_backordered = True
                        total_available += item_avail
                        if item_avail > 0:
                            await reserve_stock(self.db, self.redis, sku, req_id, item_avail)
                        inventory_reservation_total.labels(status="backordered").inc()

        # 4. Insert into DB
        now = datetime.now(timezone.utc)
        req = PurchaseRequest(
            id=req_id,
            request_type=data.request_type,
            requested_by=data.requested_by,
            department=data.department,
            vendor_id=data.vendor_id,
            amount=data.amount,
            currency=data.currency,
            spend_tier=tier_name,
            approval_chain=approval_chain,
            sla_deadline=sla_deadline,
            items=data.items,
            is_backordered=is_backordered,
            comments=data.comments,
            status="pending_approval",
            created_at=now,
            updated_at=now,
        )
        self.db.add(req)
        await self.db.commit()
        await self.db.refresh(req)

        if is_backordered and data.request_type == "hardware":
            immediate_req, backorder_req = await split_backorder(self.db, req, total_available)
            if immediate_req:
                req = immediate_req
            elif backorder_req:
                req = backorder_req

        # 5. Publish approval.requested Kafka event
        try:
            await self.producer.publish_approval_requested(req)
        except Exception as e:
            # Don't fail the request if Kafka is temporarily unavailable
            import logging
            logging.getLogger(__name__).error(f"Failed to publish approval.requested: {e}")

        # 6. If auto-approved, immediately approve and publish decided event
        if tier_name == "auto":
            req.status = "approved"
            now = datetime.now(timezone.utc)

            # Record in approval history
            history = ApprovalHistory(
                id=str(uuid.uuid4()),
                request_id=req.id,
                decision="approved",
                decided_by="system",
                decision_level="auto",
                escalated=False,
                comments="Auto-approved: amount within auto-approval threshold",
                decided_at=now,
            )
            self.db.add(history)

            # Audit log
            audit = AuditLog(
                id=str(uuid.uuid4()),
                entity_type="purchase_request",
                entity_id=req.id,
                action="auto_approved",
                performed_by="system",
                details={"tier": "auto", "amount": float(data.amount)},
            )
            self.db.add(audit)
            await self.db.commit()
            await self.db.refresh(req)

            try:
                await self.producer.publish_approval_decided(
                    req.id, "approved", "system", "auto", False, None, now
                )
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Failed to publish approval.decided: {e}")
        else:
            # 7. Start Temporal approval workflow for non-auto tiers
            try:
                from temporalio.client import Client

                temporal_client = await Client.connect(
                    settings.temporal_host, namespace=settings.temporal_namespace
                )
                await temporal_client.start_workflow(
                    "ApprovalWorkflow",
                    req.id,
                    id=f"approval-{req.id}",
                    task_queue=settings.temporal_task_queue,
                )
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(
                    f"Failed to start Temporal workflow (will retry): {e}"
                )

        return req

    async def process_decision(
        self, request_id: str, decision: str, action: ApprovalAction
    ) -> PurchaseRequest:
        """Process an approve/reject decision from an approver.
        
        Sends a signal to the running Temporal workflow, which handles
        the actual state transitions and event publishing.
        
        Args:
            request_id: UUID of the purchase request
            decision: 'approved' or 'rejected'
            action: ApprovalAction with decided_by and optional comments
            
        Returns:
            The updated PurchaseRequest
            
        Raises:
            ValueError: If request not found or not in pending state
        """
        # 1. Fetch request, validate it exists and is pending
        req = await self.get_request_with_history(request_id)
        if not req:
            raise ValueError("Request not found")
        if req.status != "pending_approval":
            raise ValueError(
                f"Request is in status '{req.status}', cannot process decision"
            )

        chain = req.approval_chain or []
        idx = req.current_approver_index

        if idx >= len(chain):
            raise ValueError("Approval chain already completed")

        # 2. Signal the Temporal workflow to process this decision
        try:
            from temporalio.client import Client

            temporal_client = await Client.connect(
                settings.temporal_host, namespace=settings.temporal_namespace
            )
            handle = temporal_client.get_workflow_handle(f"approval-{request_id}")
            await handle.signal(
                "approval_signal",
                {
                    "decision": decision,
                    "decided_by": action.decided_by,
                    "comments": action.comments,
                },
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Failed to signal Temporal workflow: {e}")
            # Fallback: process directly without Temporal
            await self._process_decision_direct(req, decision, action)

        # Refresh to get latest state (Temporal may have updated it)
        await self.db.refresh(req)
        return req

    async def _process_decision_direct(
        self, req: PurchaseRequest, decision: str, action: ApprovalAction
    ):
        """Fallback: process a decision directly without Temporal.
        
        Used when the Temporal server is unavailable. Handles the full
        decision flow inline.
        """
        chain = req.approval_chain or []
        idx = req.current_approver_index
        expected_approver = chain[idx] if idx < len(chain) else "unknown"
        decision_level = f"level_{idx + 1}_{expected_approver}"
        now = datetime.now(timezone.utc)

        # Record decision
        history = ApprovalHistory(
            id=str(uuid.uuid4()),
            request_id=req.id,
            decision=decision,
            decided_by=action.decided_by,
            decision_level=decision_level,
            escalated=False,
            comments=action.comments,
            decided_at=now,
        )
        self.db.add(history)

        if decision == "rejected":
            req.status = "rejected"
        elif idx + 1 >= len(chain):
            # Last approver approved — fully approved
            req.status = "approved"
        else:
            # More approvers in chain — advance to next
            req.current_approver_index = idx + 1

        # Audit log
        audit = AuditLog(
            id=str(uuid.uuid4()),
            entity_type="purchase_request",
            entity_id=req.id,
            action=f"approval_{decision}",
            performed_by=action.decided_by,
            details={
                "decision": decision,
                "level": decision_level,
                "escalated": False,
            },
        )
        self.db.add(audit)
        await self.db.commit()

        # Publish event
        try:
            await self.producer.publish_approval_decided(
                req.id, decision, action.decided_by, decision_level,
                False, action.comments, now
            )
        except Exception:
            pass
