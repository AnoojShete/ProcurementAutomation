"""Public endpoints for email-based approvals (Prompt 8 A5).

Exposed through the gateway at /email-action/*. Authenticates via token alone
(narrow exemption from JWT auth middleware).
GET renders a Jinja2 confirmation page and MUST NEVER change state.
POST /decide performs the decision inside an atomic transaction with row locking.
"""
import os
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import EmailActionToken, PurchaseRequest, Vendor
from app.schemas import ApprovalAction
from app.services import approval_authority as authority
from app.services.approval_service import ApprovalService
from app.services.email_action_token_service import (
    evaluate_step_up,
    get_public_base_url,
    hash_token,
)

logger = logging.getLogger(__name__)

router = APIRouter()

TEMPLATES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates", "email_action"
)

jinja_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(["html", "xml"]),
)

SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'"
    ),
}


def _html_response(content: str, status_code: int = 200) -> HTMLResponse:
    # No cookies are set or read on these endpoints, so cookie-based CSRF does not apply.
    return HTMLResponse(content=content, status_code=status_code, headers=SECURITY_HEADERS)


def _render_status(title: str, message: str, status_code: int, icon: str = "ℹ️") -> HTMLResponse:
    template = jinja_env.get_template("status_page.html")
    portal_url = f"{get_public_base_url()}/app/login"
    html = template.render(title=title, message=message, portal_url=portal_url, icon=icon)
    return _html_response(html, status_code=status_code)


async def _check_rate_limit(request: Request) -> None:
    """Enforces Redis rate limiting (30 requests/minute per client IP)."""
    redis_client = getattr(request.app.state, "redis", None)
    if redis_client is None:
        return
    client_ip = request.headers.get("x-real-ip") or (request.client.host if request.client else "unknown")
    key = f"rate_limit:email_action:{client_ip}"
    try:
        count = await redis_client.incr(key)
        if count == 1:
            await redis_client.expire(key, 60)
        if count > 30:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please try again in a minute.",
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Rate limit check encountered error: {e}")


async def _fetch_vendor_clearance(
    vendor_id: Optional[str],
    spend_amount: Optional[float] = None,
    currency: str = "INR",
) -> tuple[dict, bool]:
    """Calls contract-risk-agent GET /vendors/{vendor_id}/clearance?purpose=purchase (Prompt 9C Section C3)."""
    if not vendor_id:
        return {"cleared": False, "final_band": "Unrated", "risk_band": "Unrated", "reasons": ["no_vendor_id"]}, True
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
            return {"cleared": False, "final_band": "Unrated", "risk_band": "Unrated", "reasons": ["clearance_endpoint_error"]}, True
    except Exception as e:
        logger.warning(f"Could not reach contract-risk-agent for vendor clearance: {e}")
        return {"cleared": False, "final_band": "Unrated", "risk_band": "Unrated", "reasons": ["service_unreachable"]}, True


async def _fetch_vendor_risk(vendor_id: Optional[str]) -> tuple[Optional[str], bool]:
    """Compatibility wrapper fetching clearance and returning (risk_band, failed)."""
    cl, failed = await _fetch_vendor_clearance(vendor_id)
    return cl.get("final_band") or cl.get("risk_band"), (failed or not cl.get("cleared", False))


@router.get("/{token}", response_class=HTMLResponse)
async def get_email_action_page(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Renders the HTML decision page for an email action token.

    GET MUST NOT CHANGE ANY STATE. Prefetching scanners leave the request pending
    and the token completely unused.
    """
    await _check_rate_limit(request)

    tok_hash = hash_token(token)
    stmt = select(EmailActionToken).where(EmailActionToken.token_hash == tok_hash)
    res = await db.execute(stmt)
    tok_row = res.scalar_one_or_none()

    if not tok_row:
        # Generic 404 (never reveal whether a token or request exists)
        return _render_status(
            title="Link Not Found",
            message="This action link is invalid or does not exist.",
            status_code=404,
            icon="❓",
        )

    now = datetime.now(timezone.utc)
    # Check revoked
    if tok_row.revoked_at:
        reason = tok_row.revoked_reason or "revoked"
        if reason == "superseded":
            msg = "A newer approval link has been sent to you. Please check your latest email."
        elif "decided" in reason:
            msg = "This request was already decided on the portal or via email."
        else:
            msg = f"This link was revoked ({reason})."
        return _render_status(title="Link Revoked", message=msg, status_code=410, icon="⚠️")

    # Check already used
    if tok_row.used_at:
        msg = f"This link was already used to {tok_row.used_action or 'decide'} this request at {tok_row.used_at.strftime('%Y-%m-%d %H:%M UTC')}."
        return _render_status(title="Link Already Used", message=msg, status_code=410, icon="✅")

    # Check expired (database server time / UTC comparison)
    exp = tok_row.expires_at if tok_row.expires_at.tzinfo else tok_row.expires_at.replace(tzinfo=timezone.utc)
    if exp <= now:
        msg = f"This action link expired at {exp.strftime('%Y-%m-%d %H:%M UTC')}."
        return _render_status(title="Link Expired", message=msg, status_code=410, icon="⏰")

    # Load request
    req = await db.get(PurchaseRequest, tok_row.request_id)
    if not req or req.status != "pending_approval":
        status_name = (req.status if req else "not found").replace("_", " ")
        msg = f"This request is no longer pending approval (current status: {status_name})."
        return _render_status(title="Request Already Processed", message=msg, status_code=410, icon="ℹ️")

    if req.current_approver_index != tok_row.step_index:
        msg = "This approval step has already been completed or escalated."
        return _render_status(title="Step Completed", message=msg, status_code=410, icon="ℹ️")

    # Load vendor name & risk band
    vendor_name = None
    if req.vendor_id:
        v = await db.get(Vendor, req.vendor_id)
        if v:
            vendor_name = v.name

    risk_band, risk_failed = await _fetch_vendor_risk(req.vendor_id)

    # Check over budget
    over_budget = getattr(req, "is_over_budget", False) or False

    # Evaluate Step-Up rules
    email_enabled, step_up_required, step_up_reason = evaluate_step_up(
        amount=req.amount,
        over_budget=over_budget,
        vendor_risk_band=risk_band,
        risk_lookup_failed=risk_failed,
    )

    portal_url = f"{get_public_base_url()}/app/requests/{req.id}"

    template = jinja_env.get_template("decision_page.html")
    html = template.render(
        token=token,
        request_id=req.id,
        requested_by=req.requested_by,
        department=req.department,
        vendor_name=vendor_name,
        vendor_risk_band=risk_band,
        amount=float(req.amount),
        currency=req.currency,
        over_budget=over_budget,
        items=req.items or [],
        approver_id=tok_row.approver_id,
        expires_at=exp.strftime("%Y-%m-%d %H:%M UTC"),
        email_action_enabled=email_enabled,
        step_up_required=step_up_required,
        step_up_reason=step_up_reason,
        portal_url=portal_url,
    )
    return _html_response(html)


@router.post("/{token}/decide", response_class=HTMLResponse)
async def decide_email_action(
    token: str,
    request: Request,
    decision: str = Form(...),
    comment: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """Executes the approve/reject decision for an email action token.

    Performs validation and state mutation inside one atomic database transaction
    with FOR UPDATE row locking.
    """
    await _check_rate_limit(request)

    decision_norm = decision.strip().lower()
    if decision_norm not in ("approve", "reject"):
        return _render_status("Invalid Decision", "Decision must be 'approve' or 'reject'.", 400)

    if decision_norm == "reject" and not (comment and comment.strip()):
        return _render_status(
            "Comment Required",
            "A comment or justification is required when rejecting a request.",
            400,
        )

    action_decision = "approved" if decision_norm == "approve" else "rejected"
    tok_hash = hash_token(token)
    client_ip = request.headers.get("x-real-ip") or (request.client.host if request.client else "unknown")
    user_agent = request.headers.get("user-agent", "unknown")

    # 1. SELECT token FOR UPDATE
    stmt = select(EmailActionToken).where(EmailActionToken.token_hash == tok_hash).with_for_update()
    res = await db.execute(stmt)
    tok_row = res.scalar_one_or_none()

    if not tok_row:
        return _render_status("Link Not Found", "This action link is invalid or does not exist.", 404, "❓")

    now = datetime.now(timezone.utc)
    if tok_row.revoked_at:
        reason = tok_row.revoked_reason or "revoked"
        if reason == "superseded":
            msg = "A newer approval link has been sent to you. Please check your latest email."
        elif reason == "decided":
            msg = "This request was already decided on the portal or via email."
        else:
            msg = f"This link was revoked ({reason})."
        return _render_status("Link Revoked", msg, 410, "⚠️")

    if tok_row.used_at:
        return _render_status(
            "Link Already Used",
            f"This link was already used to {tok_row.used_action} this request.",
            410,
            "✅",
        )

    exp = tok_row.expires_at if tok_row.expires_at.tzinfo else tok_row.expires_at.replace(tzinfo=timezone.utc)
    if exp <= now:
        return _render_status("Link Expired", "This action link has expired.", 410, "⏰")

    # 2. Confirm request is still pending at this step
    req = await db.get(PurchaseRequest, tok_row.request_id)
    if not req or req.status != "pending_approval":
        status_name = (req.status if req else "not found").replace("_", " ")
        return _render_status("Request Already Processed", f"This request is in status '{status_name}'.", 410, "ℹ️")

    if req.current_approver_index != tok_row.step_index:
        return _render_status("Step Completed", "This step has already been completed or escalated.", 410, "ℹ️")

    # 3. Re-check authority & Segregation of Duties at ACTION time
    auth_check = await authority.check_request_authority(db, req, tok_row.approver_id, action_decision)
    if not auth_check.allowed:
        return _render_status(
            "Authority Refusal",
            f"Action not permitted: {auth_check.reason} ({auth_check.code})",
            403,
            "🚫",
        )

    # 4. Re-check Step-Up rules at ACTION time
    risk_band, risk_failed = await _fetch_vendor_risk(req.vendor_id)
    over_budget = getattr(req, "is_over_budget", False) or False
    email_enabled, step_up_required, step_up_reason = evaluate_step_up(
        amount=req.amount,
        over_budget=over_budget,
        vendor_risk_band=risk_band,
        risk_lookup_failed=risk_failed,
    )

    if not email_enabled:
        return _render_status(
            "Email Actions Disabled",
            "Email actions are currently disabled. Please sign in to the portal.",
            403,
            "🚫",
        )

    if step_up_required and action_decision == "approved":
        return _render_status(
            "Step-Up Required",
            f"Approval requires portal login: {step_up_reason}",
            403,
            "🔒",
        )

    # 5. Call the shared decision function with channel "email"
    producer = getattr(request.app.state, "kafka_producer", None)
    redis_client = getattr(request.app.state, "redis", None)
    approval_svc = ApprovalService(db, producer, redis_client)
    action_data = ApprovalAction(decided_by=tok_row.approver_id, comments=comment)

    try:
        await approval_svc.process_decision(
            request_id=req.id,
            decision=action_decision,
            action=action_data,
            channel="email",
            actor_role="approver",
        )
    except Exception as e:
        logger.error(f"Failed to execute email decision: {e}", exc_info=True)
        await db.rollback()
        return _render_status("Execution Error", f"Failed to record decision: {e}", 500, "❌")

    # 6. Mark token used in the same transaction
    tok_row.used_at = now
    tok_row.used_action = action_decision
    tok_row.used_ip = client_ip
    tok_row.used_user_agent = user_agent

    # 7. Commit transaction
    await db.commit()

    # 8. Send confirmation email to approver (B3)
    if producer is not None:
        try:
            await producer.publish_notification(
                recipient=tok_row.approver_id,
                channel="email",
                template_name="email_action_confirmation",
                template_context={
                    "decision": action_decision,
                    "request_id": req.id,
                    "timestamp": now.strftime("%Y-%m-%d %H:%M UTC"),
                    "ip_address": client_ip,
                },
                priority="urgent",
                related_entity_id=req.id,
            )
        except Exception as e:
            logger.warning(f"Could not publish email confirmation notification: {e}")

    past_tense = "approved" if action_decision == "approved" else "rejected"
    return _render_status(
        title=f"Request {past_tense.capitalize()}",
        message=f"You successfully {past_tense} request {req.id[:8]} via email action. A confirmation email has been dispatched to {tok_row.approver_id}.",
        status_code=200,
        icon="✅",
    )
