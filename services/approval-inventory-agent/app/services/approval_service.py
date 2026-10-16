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

from shared.eventing import staged
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
        from shared.rules_engine import get_rule
        tiers = get_rule("approval.spend_tiers", fallback=None)
        if not tiers:
            tiers = load_spend_tiers()
        for tier in tiers:
            name = tier.get("tier_name") or tier.get("name")
            chain = tier.get("required_roles") if "required_roles" in tier else tier.get("approval_chain", [])
            max_amt = tier.get("max_amount")
            if max_amt is None or amount <= float(max_amt):
                return name, list(chain)
        last_name = tiers[-1].get("tier_name") or tiers[-1].get("name")
        last_chain = tiers[-1].get("required_roles") if "required_roles" in tiers[-1] else tiers[-1].get("approval_chain", [])
        return last_name, list(last_chain)

    async def list_requests(self, limit: int = 100, requested_by: str | None = None) -> list[PurchaseRequest]:
        """Purchase requests (all, or only `requested_by`'s), most recently
        created first — backs the tracking dashboard."""
        stmt = select(PurchaseRequest).options(selectinload(PurchaseRequest.approval_history))
        if requested_by is not None:
            from sqlalchemy import func
            stmt = stmt.where(func.lower(PurchaseRequest.requested_by) == requested_by.lower())
        stmt = stmt.order_by(PurchaseRequest.created_at.desc().nulls_last()).limit(limit)
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

    async def create_request(self, data: CreatePurchaseRequest, document_id: str | None = None) -> PurchaseRequest:
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
        if data.request_type == "reinstate":
            tier_name = "manager"
            approval_chain = ["dept_manager"]
            license_id = None
            if data.items:
                for item in data.items:
                    if "license_id" in item:
                        license_id = item["license_id"]
                        break
            if license_id:
                from app.models import License
                stmt = select(License).where(License.id == license_id)
                result = await self.db.execute(stmt)
                lic = result.scalar_one_or_none()
                if lic:
                    available_seats = lic.total_seats - lic.assigned_seats
                    if available_seats <= 0:
                        data.request_type = "license"
                        tier_name, approval_chain = self.determine_spend_tier(data.amount)
        else:
            tier_name, approval_chain = self.determine_spend_tier(data.amount)

        # 2. Calculate SLA deadline
        config = load_config()
        from shared.rules_engine import get_rule
        sla_hours = int(get_rule("approval.sla_escalation_hours", fallback=config.get("sla", {}).get("approval_timeout_hours", 48)))
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

        # 4. Insert into DB. Nothing in stock at all: the request itself waits
        # for stock — no split into an empty ₹0 "immediate" request that
        # would sit in the approval queue.
        nothing_in_stock = is_backordered and data.request_type == "hardware" and total_available == 0
        now = datetime.now(timezone.utc)
        req = PurchaseRequest(
            id=req_id,
            # The source quote, for requests created from a drop-folder
            # document or uploaded in the creation wizard.
            document_id=document_id or data.document_id,
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
            comments=(f"Backordered: no stock; {data.comments}" if data.comments else "Backordered: no stock")
            if nothing_in_stock else data.comments,
            status="backordered" if nothing_in_stock else "pending_approval",
            created_at=now,
            updated_at=now,
        )
        self.db.add(req)
        # Events go through the outbox in the same transaction as the change
        # they announce (shared/eventing/outbox.py), so a Kafka outage or a
        # crash after commit can't lose them; the relay retries until sent.
        outbox = staged(self.producer, self.db)
        if nothing_in_stock and outbox is not None:
            # Announced like a backordered split portion; it enters approval
            # when stock arrives (backordered -> pending_approval).
            await outbox.publish_approval_requested(req)
        await self.db.commit()
        await self.db.refresh(req)

        if nothing_in_stock:
            return await self._reloaded(req.id)

        if is_backordered and data.request_type == "hardware":
            immediate_req, backorder_req = await split_backorder(self.db, req, total_available)
            if immediate_req:
                req = immediate_req  # The immediate portion goes through approval flow

            # GAP-A8 fix: also publish approval.requested for the backordered portion
            # so notification-agent and other services know about it.
            if backorder_req and outbox is not None:
                await outbox.publish_approval_requested(backorder_req)

        # 5. approval.requested for the immediate / main request (outbox: sent
        # by the relay once Kafka is reachable).
        if outbox is not None:
            await outbox.publish_approval_requested(req)
            await self.db.commit()

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
            outbox = staged(self.producer, self.db)
            if outbox is not None:
                await outbox.publish_approval_decided(req.id, "approved", "system", "auto", False, None, now)
            await self.db.commit()
            await self.db.refresh(req)
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

        return await self._reloaded(req.id)

    async def _reloaded(self, request_id: str) -> PurchaseRequest:
        """The request with its history loaded. After a backorder split the
        returned request is a child whose approval_history was never loaded,
        and serialising it would lazy-load outside the async context (the
        API returned 400 while the request had in fact been created)."""
        stmt = (select(PurchaseRequest).options(selectinload(PurchaseRequest.approval_history))
                .where(PurchaseRequest.id == request_id).execution_options(populate_existing=True))
        return (await self.db.execute(stmt)).scalar_one()

    async def process_decision(
        self, request_id: str, decision: str, action: ApprovalAction,
        channel: str = "portal", actor_role: str = "approver"
    ) -> PurchaseRequest:
        """Process an approve/reject decision from an approver (portal or email action).
        
        Reuses the exact same business logic: budget checks, segregation of duties,
        delegation resolution, atomic row locks, Temporal signal, Kafka publishing,
        and audit logging.
        
        Args:
            request_id: UUID of the purchase request
            decision: 'approved' or 'rejected'
            action: ApprovalAction with decided_by and optional comments
            channel: 'portal' or 'email'
            actor_role: role of the decider ('approver', 'finance', 'admin')
            
        Returns:
            The updated PurchaseRequest
            
        Raises:
            ValueError: If request not found or not in pending state
            AuthorityError: If authority check fails
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

        # 1b. Authority + separation of duties (app/services/approval_authority.py):
        # right level, within limit, not your own request, one person per level.
        from app.services.approval_authority import AuthorityError, check_request_authority
        authority = await check_request_authority(self.db, req, action.decided_by, decision)
        if not authority.allowed:
            raise AuthorityError(authority)

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
                    # Authority was checked for this level only.
                    "level_index": idx,
                    "channel": channel,
                },
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Failed to signal Temporal workflow: {e}")
            # Fallback: process directly without Temporal
            await self._process_decision_direct(req, decision, action, channel=channel)

        # 3. Prompt 8 A6: Revoke email action tokens on decision
        from app.services.email_action_token_service import revoke_tokens
        await revoke_tokens(self.db, request_id, reason=f"decided_via_{channel}")
        await self.db.commit()

        # Refresh to get latest state (Temporal or direct fallback updated it)
        await self.db.refresh(req)
        return req

    async def _process_decision_direct(
        self, req: PurchaseRequest, decision: str, action: ApprovalAction,
        channel: str = "portal"
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
                "channel": channel,
            },
        )
        self.db.add(audit)
        # approval.decided starts contract generation — it must not be lost
        # (it used to be sent after the commit with errors ignored).
        outbox = staged(self.producer, self.db)
        if outbox is not None:
            await outbox.publish_approval_decided(
                req.id, decision, action.decided_by, decision_level,
                False, action.comments, now, decision_channel=channel
            )
        await self.db.commit()

    async def decline_reclaim(self, request_id: str, requested_by: str) -> PurchaseRequest:
        from app.models import License
        from shared.rules_engine import get_rule
        req = await self.get_request_with_history(request_id)
        if not req:
            raise ValueError("Request not found")
        if req.request_type != "reclaim":
            raise ValueError("Only reclaim requests can be declined via this endpoint")
        if req.status != "pending_grace_period":
            raise ValueError("Reclaim request is no longer in grace period")

        now = datetime.now(timezone.utc)
        req.status = "cancelled"
        
        try:
            from temporalio.client import Client
            temporal_client = await Client.connect(
                settings.temporal_host, namespace=settings.temporal_namespace
            )
            handle = temporal_client.get_workflow_handle(f"approval-{request_id}")
            await handle.signal(
                "approval_signal",
                {
                    "decision": "cancelled",
                    "decided_by": requested_by,
                    "comments": "Declined by user during grace period",
                },
            )
        except Exception:
            pass
            
        if req.items:
            for item in req.items:
                if "license_id" in item:
                    stmt = select(License).where(License.id == item["license_id"])
                    result = await self.db.execute(stmt)
                    lic = result.scalar_one_or_none()
                    if lic:
                        cooldown_days = int(get_rule("license.reclaim_cooldown_days", fallback=45))
                        lic.reclaim_cooldown_until = now + timedelta(days=cooldown_days)

        audit = AuditLog(
            id=str(uuid.uuid4()),
            entity_type="purchase_request",
            entity_id=req.id,
            action="reclaim_declined",
            performed_by=requested_by,
            details={"reason": "Declined by user during grace period"},
        )
        self.db.add(audit)

        # Prompt 8 A6: revoke any active tokens when reclaim is declined
        from app.services.email_action_token_service import revoke_tokens
        await revoke_tokens(self.db, request_id, reason="reclaim_declined")

        await self.db.commit()
        await self.db.refresh(req)
        return req


