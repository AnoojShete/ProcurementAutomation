from temporalio import workflow
from datetime import timedelta
from typing import Optional
import asyncio
from dataclasses import dataclass

with workflow.unsafe.imports_passed_through():
    from app.workflows.activities import (
        fetch_request_details, update_request_status,
        record_approval_decision, publish_approval_decided_event,
        publish_notification_event, release_inventory_lock,
        NotificationInput
    )

@dataclass
class ApprovalSignal:
    decision: str  # approved or rejected
    decided_by: str
    # Temporal's payload converter checks the annotation strictly — `str`
    # with a `None` default fails to decode a signal sent without
    # comments, since None doesn't match `str`.
    comments: Optional[str] = None

@workflow.defn
class ApprovalWorkflow:
    """Orchestrates multi-level approval with SLA-based escalation.
    
    For each approver in the chain:
    1. Wait for approval signal OR SLA timeout
    2. If signal received: process decision
    3. If timeout: auto-escalate to next level
    4. If rejected at any level: reject the whole request
    5. If approved by all levels: fully approve
    """
    
    def __init__(self):
        self._approval_signal: ApprovalSignal | None = None
    
    @workflow.signal
    async def approval_signal(self, signal: ApprovalSignal):
        self._approval_signal = signal
    
    async def _handle_escalation(self, request_id: str, approver_id: str, decision_level: str, index: int, total: int):
        # Escalate if not the last approver
        escalated = True
        decision = "auto_escalated"
        decided_by = "system"
        
        await workflow.execute_activity(
            record_approval_decision,
            args=[request_id, decision, decided_by, decision_level, escalated, "SLA Breached - Auto Escalated"],
            start_to_close_timeout=timedelta(seconds=10)
        )
        await workflow.execute_activity(
            publish_approval_decided_event,
            args=[request_id, decision, decided_by, decision_level, escalated, "SLA Breached"],
            start_to_close_timeout=timedelta(seconds=10)
        )
        
        notification_input = NotificationInput(
            recipient=approver_id,
            channel="email",
            template_name="sla_breach_escalation",
            template_context={"request_id": request_id, "decision_level": decision_level},
            priority="urgent",
            related_entity_id=request_id
        )
        await workflow.execute_activity(
            publish_notification_event,
            args=[notification_input],
            start_to_close_timeout=timedelta(seconds=10)
        )
        
    async def _handle_rejection(self, request_id: str, signal: ApprovalSignal, decision_level: str):
        await workflow.execute_activity(
            record_approval_decision,
            args=[request_id, 'rejected', signal.decided_by, decision_level, False, signal.comments],
            start_to_close_timeout=timedelta(seconds=10)
        )
        await workflow.execute_activity(
            publish_approval_decided_event,
            args=[request_id, 'rejected', signal.decided_by, decision_level, False, signal.comments],
            start_to_close_timeout=timedelta(seconds=10)
        )
        await workflow.execute_activity(
            update_request_status,
            args=[request_id, 'rejected', -1],
            start_to_close_timeout=timedelta(seconds=10)
        )

    @workflow.run
    async def run(self, request_id: str) -> dict:
        # 1. Fetch request details
        request = await workflow.execute_activity(
            fetch_request_details, request_id,
            start_to_close_timeout=timedelta(seconds=10)
        )
        
        approval_chain = request['approval_chain']
        sla_hours = request.get('sla_hours', 48)
        
        # 2. Iterate through approval chain
        for i, approver_id in enumerate(approval_chain):
            decision_level = f"level_{i+1}_{approver_id}"
            
            # Update status to show current approver
            await workflow.execute_activity(
                update_request_status,
                args=[request_id, 'pending_approval', i],
                start_to_close_timeout=timedelta(seconds=10)
            )
            
            # Reset signal
            self._approval_signal = None
            
            # Wait for signal or timeout
            try:
                await workflow.wait_condition(
                    lambda: self._approval_signal is not None,
                    timeout=timedelta(hours=sla_hours)
                )
            except asyncio.TimeoutError:
                # SLA breached - auto-escalate
                await self._handle_escalation(request_id, approver_id, decision_level, i, len(approval_chain))
                continue
            
            signal = self._approval_signal
            
            if signal.decision == 'rejected':
                # Rejected - stop the chain
                await self._handle_rejection(request_id, signal, decision_level)
                return {"request_id": request_id, "status": "rejected"}
            
            # Approved at this level - record and continue
            await workflow.execute_activity(
                record_approval_decision,
                args=[request_id, 'approved', signal.decided_by, decision_level, False, signal.comments],
                start_to_close_timeout=timedelta(seconds=10)
            )
            await workflow.execute_activity(
                publish_approval_decided_event,
                args=[request_id, 'approved', signal.decided_by, decision_level, False, signal.comments],
                start_to_close_timeout=timedelta(seconds=10)
            )
        
        # All levels approved
        await workflow.execute_activity(
            update_request_status,
            args=[request_id, 'approved', len(approval_chain)],
            start_to_close_timeout=timedelta(seconds=10)
        )
        
        return {"request_id": request_id, "status": "approved"}
