"""Bulk approval business logic (Prompt 10 Section 1.2, 1.4).

Enforces:
- Dynamic rule evaluations (limits read at execution time via get_rule).
- One eligibility function bulk_eligibility used across portal, email batch, and execute endpoint.
- Per-item isolated execution in ascending ID order.
- Running caps on max items and max batch total.
- Auto-sign acknowledgement check for final finance approval under active mandate.
- Idempotency per approver.
- Single shared entry point: ApprovalService.process_decision (never writes approvals directly to DB).
"""
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import HTTPException, status
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.models import (
    ApprovalBatch,
    ApprovalBatchItem,
    Document,
    PurchaseRequest,
    Vendor,
)
from app.schemas import ApprovalAction
from app.services.approval_authority import check_request_authority
from app.services.approval_service import ApprovalService
from shared.rules_engine import get_rule

logger = logging.getLogger(__name__)


async def fetch_vendor_clearance(
    vendor_id: Optional[str],
    spend_amount: Optional[float] = None,
    currency: str = "INR",
) -> tuple[dict, bool]:
    """Calls contract-risk-agent GET /vendors/{vendor_id}/clearance?purpose=purchase."""
    if not vendor_id:
        return {"cleared": False, "reasons": ["no_vendor_id"]}, True
    clearance_url = f"http://contract-risk-agent:8003/vendors/{vendor_id}/clearance"
    params: dict = {"purpose": "purchase", "currency": currency}
    if spend_amount is not None:
        params["spend_amount"] = spend_amount
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(clearance_url, params=params)
            if resp.status_code == 200:
                data = resp.json().get("data", {})
                return data, False
            return {"cleared": False, "reasons": ["clearance_endpoint_error"]}, True
    except Exception as e:
        logger.warning(f"Could not reach contract-risk-agent for vendor clearance: {e}")
        return {"cleared": False, "reasons": ["service_unreachable"]}, True


async def bulk_eligibility(
    db: AsyncSession,
    request: PurchaseRequest,
    approver_id: str,
    approver_role: str,
    now: Optional[datetime] = None,
) -> Tuple[bool, List[str], List[str]]:
    """Single shared eligibility function for bulk approval (Prompt 10 Section 1.2).

    Eligible only if ALL are true:
    - approval.bulk_approve_enabled; approver or finance role
    - pending at step where THIS user is the active approver
    - amount <= approval.bulk_approve_max_amount in base currency (INR)
    - not over_budget
    - requester is not the approver (segregation of duties)
    - request type not in approval.bulk_excluded_request_types
    - vendor clearance returns cleared=true (fail closed)
    - no open invoice mismatch (unmatched_invoice false)

    Returns:
        (eligible: bool, reason_codes: list[str], reason_labels: list[str])
    """
    now = now or datetime.now(timezone.utc)
    reason_codes: List[str] = []
    reason_labels: List[str] = []

    # 1. Bulk approve enabled
    bulk_enabled = get_rule("approval.bulk_approve_enabled", fallback=True)
    if not bulk_enabled:
        reason_codes.append("bulk_disabled")
        reason_labels.append("Bulk approval is currently disabled")

    # 2. Role check
    role = (approver_role or "").lower()
    if role not in ("approver", "finance", "admin"):
        reason_codes.append("role_not_allowed")
        reason_labels.append("Only Approver and Finance roles can approve in bulk")

    # 3. Status check
    if request.status != "pending_approval":
        reason_codes.append("not_pending")
        reason_labels.append(f"Request is in status '{request.status}', not pending approval")

    # 4. Chain & active step authority check
    chain = request.approval_chain or []
    idx = request.current_approver_index
    if idx >= len(chain):
        reason_codes.append("chain_completed")
        reason_labels.append("Approval chain already completed")
    else:
        # Check authority (level, spend limit, delegation, segregation of duties)
        auth = await check_request_authority(db, request, approver_id, "approved")
        if not auth.allowed:
            reason_codes.append(auth.reason_code)
            reason_labels.append(auth.reason_message or "Not authorised to approve this request")

    # 5. Amount & Currency cap
    bulk_max_amount = float(get_rule("approval.bulk_approve_max_amount", fallback=25000.0))
    currency = (request.currency or "INR").upper()
    if currency != "INR":
        reason_codes.append("foreign_currency")
        reason_labels.append("Foreign currency requests must be approved individually")
    elif float(request.amount or 0) > bulk_max_amount:
        reason_codes.append("above_bulk_limit")
        reason_labels.append(f"Above bulk limit of INR {bulk_max_amount:,.0f}, approve individually")

    # 6. Budget status (over_budget cannot be bulk approved)
    if request.budget_status == "over":
        reason_codes.append("over_budget")
        reason_labels.append("Over budget: requires individual finance review")

    # 7. Own request check (segregation of duties)
    if request.requested_by == approver_id or (request.requested_by_user_id and request.requested_by_user_id == approver_id):
        if "own_request" not in reason_codes:
            reason_codes.append("own_request")
            reason_labels.append("You requested this")

    # 8. Excluded request types
    excluded_types = get_rule("approval.bulk_excluded_request_types", fallback=[])
    if isinstance(excluded_types, list) and request.request_type in excluded_types:
        reason_codes.append("excluded_request_type")
        reason_labels.append(f"Request type '{request.request_type}' is excluded from bulk approval")

    # 9. Vendor clearance check (fail closed)
    if request.vendor_id:
        clearance_data, failed = await fetch_vendor_clearance(
            str(request.vendor_id),
            spend_amount=float(request.amount or 0),
            currency=currency,
        )
        if failed or not clearance_data.get("cleared", False):
            reason_codes.append("vendor_not_cleared")
            reasons = clearance_data.get("reasons", [])
            label = f"Vendor not cleared ({', '.join(reasons)})" if reasons else "Vendor not cleared"
            reason_labels.append(label)

    # 10. Open invoice mismatch check
    if request.document_id:
        doc = await db.get(Document, request.document_id)
        if doc and doc.extracted and doc.extracted.get("unmatched_invoice"):
            reason_codes.append("unmatched_invoice")
            reason_labels.append("Invoice has unmatched lines or variance")

    eligible = len(reason_codes) == 0
    return eligible, reason_codes, reason_labels


async def execute_bulk_decision(
    db: AsyncSession,
    producer: Any,
    approver_id: str,
    approver_role: str,
    request_ids: List[str],
    idempotency_key: str,
    channel: str = "portal",
    email_batch_token_id: Optional[str] = None,
    comment: Optional[str] = None,
    acknowledged_auto_sign: bool = False,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> Dict[str, Any]:
    """Executes bulk approval decision (Prompt 10 Section 1.4)."""
    now = datetime.now(timezone.utc)

    # 1. Idempotency check: return existing batch if already executed
    stmt_existing = select(ApprovalBatch).where(
        ApprovalBatch.approver_id == approver_id,
        ApprovalBatch.idempotency_key == idempotency_key,
    )
    existing_batch = (await db.execute(stmt_existing)).scalar_one_or_none()
    if existing_batch:
        stmt_items = select(ApprovalBatchItem).where(ApprovalBatchItem.batch_id == existing_batch.id)
        items = (await db.execute(stmt_items)).scalars().all()
        return {
            "batch_id": str(existing_batch.id),
            "status": existing_batch.status,
            "count_requested": existing_batch.count_requested,
            "count_approved": existing_batch.count_approved,
            "count_skipped": existing_batch.count_skipped,
            "total_approved_amount": float(existing_batch.total_approved_amount),
            "items": [
                {
                    "request_id": str(item.request_id),
                    "result": item.result,
                    "reason_code": item.reason_code,
                    "decided_at": item.decided_at.isoformat() if item.decided_at else None,
                }
                for item in items
            ],
            "idempotent_replay": True,
        }

    # 2. Rule limits & validations
    max_items = int(get_rule("approval.bulk_approve_max_items", fallback=25))
    max_batch_total = float(get_rule("approval.bulk_approve_max_batch_total", fallback=250000.0))
    actions_per_hour = int(get_rule("approval.bulk_actions_per_hour", fallback=20))

    if len(request_ids) > max_items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot process more than {max_items} requests in a single batch (received {len(request_ids)}).",
        )

    # 3. Rate limiting per approver per hour
    one_hour_ago = now - timedelta(hours=1)
    rate_stmt = select(func.count(ApprovalBatch.id)).where(
        ApprovalBatch.approver_id == approver_id,
        ApprovalBatch.created_at >= one_hour_ago,
    )
    batch_count_hour = (await db.execute(rate_stmt)).scalar() or 0
    if batch_count_hour >= actions_per_hour:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Bulk approval rate limit reached ({actions_per_hour} batches/hour). Please try again later.",
        )

    # 4. Create batch record in 'executing' state
    batch_id = str(uuid.uuid4())
    rules_snapshot = {
        "bulk_approve_max_amount": float(get_rule("approval.bulk_approve_max_amount", fallback=25000.0)),
        "bulk_approve_max_items": max_items,
        "bulk_approve_max_batch_total": max_batch_total,
    }
    batch = ApprovalBatch(
        id=batch_id,
        approver_id=approver_id,
        approver_role=approver_role,
        channel=channel,
        email_batch_token_id=email_batch_token_id,
        idempotency_key=idempotency_key,
        requested_ids=request_ids,
        status="executing",
        count_requested=len(request_ids),
        count_approved=0,
        count_skipped=0,
        total_approved_amount=0.0,
        rules_snapshot=rules_snapshot,
        ip=ip,
        user_agent=user_agent,
        acknowledged_auto_sign=acknowledged_auto_sign,
        created_at=now,
    )
    db.add(batch)
    await db.commit()

    # 5. Process items in ascending UUID order
    sorted_request_ids = sorted(request_ids)
    running_total = 0.0
    count_approved = 0
    count_skipped = 0
    item_results: List[Dict[str, Any]] = []

    # Pre-check auto-sign acknowledgement: if role is finance and auto-sign is enabled
    auto_sign_enabled = get_rule("contract.auto_sign_enabled", fallback=False)
    if auto_sign_enabled and approver_role.lower() == "finance" and not acknowledged_auto_sign:
        # Check if any request in batch would complete the approval chain
        auto_sign_candidates = []
        for req_id in sorted_request_ids:
            req = await db.get(PurchaseRequest, req_id)
            if req and req.status == "pending_approval":
                chain = req.approval_chain or []
                if req.current_approver_index + 1 >= len(chain):
                    auto_sign_candidates.append(req_id)
        if auto_sign_candidates:
            # Rollback batch or mark failed
            batch.status = "failed"
            await db.commit()
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "message": "Auto-signing acknowledgement is required for contracts that will be automatically signed upon finance approval.",
                    "auto_sign_request_ids": auto_sign_candidates,
                },
            )

    approval_service = ApprovalService(db, producer)

    for req_id in sorted_request_ids:
        item_result = "skipped"
        reason_code = None
        decision_id = None
        step_idx = 0

        # Isolated fresh session per item
        async with async_session_factory() as item_session:
            try:
                # Row lock with FOR UPDATE
                stmt_req = select(PurchaseRequest).where(PurchaseRequest.id == req_id).with_for_update()
                res = await item_session.execute(stmt_req)
                req = res.scalar_one_or_none()

                if not req:
                    item_result = "skipped"
                    reason_code = "not_found"
                else:
                    step_idx = req.current_approver_index
                    amount = float(req.amount or 0)

                    # Running caps check
                    if count_approved >= max_items:
                        item_result = "skipped"
                        reason_code = "batch_cap_reached_items"
                    elif running_total + amount > max_batch_total:
                        item_result = "skipped"
                        reason_code = "batch_cap_reached_amount"
                    else:
                        # Re-run eligibility on fresh locked row
                        eligible, codes, labels = await bulk_eligibility(
                            item_session, req, approver_id, approver_role, now
                        )
                        if not eligible:
                            item_result = "skipped"
                            reason_code = codes[0] if codes else "ineligible"
                        else:
                            # Execute via shared decision function
                            action = ApprovalAction(
                                decided_by=approver_id,
                                comments=comment or f"Bulk approved via {channel}",
                                channel=channel,
                            )
                            svc = ApprovalService(item_session, producer)
                            await svc.process_decision(
                                request_id=req_id,
                                decision="approved",
                                action=action,
                                channel=channel,
                                actor_role=approver_role,
                            )
                            item_result = "approved"
                            decision_id = str(uuid.uuid4())
                            running_total += amount
                            count_approved += 1

            except Exception as e:
                logger.error(f"Error processing bulk item {req_id}: {e}", exc_info=True)
                item_result = "failed"
                reason_code = "execution_error"

        if item_result != "approved":
            count_skipped += 1

        item_results.append({
            "request_id": req_id,
            "step_index": step_idx,
            "result": item_result,
            "reason_code": reason_code,
            "decision_id": decision_id,
            "decided_at": now,
        })

    # 6. Save batch items and finalize batch status
    async with async_session_factory() as final_session:
        batch_record = await final_session.get(ApprovalBatch, batch_id)
        if batch_record:
            batch_record.count_approved = count_approved
            batch_record.count_skipped = count_skipped
            batch_record.total_approved_amount = running_total
            batch_record.completed_at = datetime.now(timezone.utc)
            if count_approved == len(sorted_request_ids):
                batch_record.status = "completed"
            elif count_approved > 0:
                batch_record.status = "partial"
            else:
                batch_record.status = "failed"

            for res_item in item_results:
                batch_item = ApprovalBatchItem(
                    id=str(uuid.uuid4()),
                    batch_id=batch_id,
                    request_id=res_item["request_id"],
                    step_index=res_item["step_index"],
                    result=res_item["result"],
                    reason_code=res_item["reason_code"],
                    decision_id=res_item["decision_id"],
                    decided_at=res_item["decided_at"],
                )
                final_session.add(batch_item)

            await final_session.commit()

    # 7. Send confirmation email to approver
    try:
        if producer:
            await producer.publish_notification(
                recipient=approver_id,
                channel="email",
                template_name="bulk_approval_confirmation",
                template_context={
                    "batch_id": batch_id,
                    "count_approved": count_approved,
                    "count_skipped": count_skipped,
                    "total_amount": running_total,
                    "channel": channel,
                    "timestamp": now.isoformat(),
                    "ip": ip or "unknown",
                },
                priority="normal",
                related_entity_id=batch_id,
            )
    except Exception as e:
        logger.warning(f"Failed to publish bulk approval confirmation notification: {e}")

    return {
        "batch_id": batch_id,
        "status": "completed" if count_approved == len(sorted_request_ids) else ("partial" if count_approved > 0 else "failed"),
        "count_requested": len(sorted_request_ids),
        "count_approved": count_approved,
        "count_skipped": count_skipped,
        "total_approved_amount": running_total,
        "items": [
            {
                "request_id": r["request_id"],
                "result": r["result"],
                "reason_code": r["reason_code"],
                "decided_at": r["decided_at"].isoformat(),
            }
            for r in item_results
        ],
        "idempotent_replay": False,
    }
