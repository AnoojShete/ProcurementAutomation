"""Kafka consumer for the Notification Agent.



Consumes every topic that names notification-agent as a consumer in

shared/schemas/events.md's "Consumed by" column. The task brief listed 8

of these; cross-checking the table against every row turned up two more

that also name notification-agent — document.classified and

vendor.offboarded — so all 10 are handled here:



  document.classified, license.usage.updated, approval.requested,

  approval.decided, contract.generated, contract.signed,

  contract.renewal.due, risk.score.updated, vendor.offboarded,

  notification.send



plus the feature-expansion events (budget.threshold_crossed,

contract.obligation.due, rfq.issued, rfq.awarded, goods.received).

"""

import json

import asyncio

import logging

import os

import httpx

from typing import Optional



from sqlalchemy import text



from aiokafka import AIOKafkaConsumer

from shared.kafka_security import kafka_auth_kwargs



from app.config import settings

from app.database import async_session_factory

from app.kafka.events import parse_envelope

from app.services import dispatcher, directory, routing, template_store



from shared.infra.retry import with_retry

from shared.logging.context import CorrelationContext



logger = logging.getLogger(__name__)





async def _mint_action_url(request_id: str, approver_id: str, step_index: int) -> tuple[str | None, str | None]:

    """Calls approval-inventory-agent POST /internal/email-actions/mint to obtain action_url."""

    token = os.environ.get("INTERNAL_SERVICE_TOKEN", "dev-internal-service-token-change-me")

    url = "http://approval-inventory-agent:8002/internal/email-actions/mint"

    headers = {"X-Internal-Service-Token": token}

    body = {

        "request_id": request_id,

        "approver_id": approver_id,

        "step_index": step_index,

    }

    try:

        async with httpx.AsyncClient(timeout=3.0) as client:

            resp = await client.post(url, json=body, headers=headers)

            if resp.status_code == 200:

                data = resp.json().get("data", {})

                return data.get("action_url"), data.get("expires_at")

            else:

                logger.warning(f"Minting email action token failed ({resp.status_code}): {resp.text[:200]}")

                return None, None

    except Exception as e:

        logger.warning(f"Error calling internal mint endpoint: {e}")

        return None, None





CONSUME_TOPICS = [

    "document.classified",              # published by document-vendor-agent

    "vendor.payment_details_flagged",   # published by document-vendor-agent (fraud alert)

    "license.usage.updated",            # published by approval-inventory-agent

    "approval.requested",               # published by approval-inventory-agent

    "approval.decided",                 # published by approval-inventory-agent

    "contract.generated",               # published by contract-risk-agent

    "contract.signed",                  # published by contract-risk-agent

    "contract.renewal.due",             # published by contract-risk-agent

    "risk.score.updated",               # published by contract-risk-agent

    "vendor.offboarded",                # published by contract-risk-agent

    "notification.send",                # generic fallback, published by any service

    # Feature expansion (Phases 1-3)

    "budget.threshold_crossed",         # published by approval-inventory-agent

    "contract.obligation.due",          # published by contract-risk-agent

    "rfq.issued",                       # published by approval-inventory-agent

    "rfq.awarded",                      # published by approval-inventory-agent

    "goods.received",                   # published by approval-inventory-agent

    "reminder.due",                     # published by all three agents (FR-03)

]





CONSUMER_NAME = "notification-agent"



# Whether the consumer loop is alive — read by /health. Before this, a

# failed Kafka login ended the loop silently and the service still

# reported healthy (it stopped sending for three days on Oct 14).

CONSUMER_STATE: dict = {"status": "starting", "error": None, "since": None}





def _set_state(status: str, error: str | None = None) -> None:

    from datetime import datetime, timezone

    CONSUMER_STATE.update(status=status, error=error, since=datetime.now(timezone.utc).isoformat())





async def dispatch(topic: str, event: dict) -> None:

    """Handles one event; raises on failure so deliver() retries it and

    finally dead-letters it (event_dlq) instead of dropping it."""

    event_type, payload, schema_version = parse_envelope(event)

    if schema_version != 1:

        logger.info(f"event {event_type} has schema_version={schema_version} (handled as v1-compatible)")

    handler = _HANDLERS.get(event_type)

    if handler is None:

        logger.warning(f"Unhandled event type on topic {topic}: {event_type}")

        return

    async with async_session_factory() as db:

        await handler(db, payload)





async def start_consumer(app):

    from shared.eventing import deliver

    consumer = AIOKafkaConsumer(

        *CONSUME_TOPICS,

        bootstrap_servers=settings.kafka_bootstrap_servers,

        group_id=settings.kafka_consumer_group,

        auto_offset_reset="earliest",

        session_timeout_ms=60000,

        heartbeat_interval_ms=10000,

        max_poll_interval_ms=600000,

        value_deserializer=lambda v: json.loads(v.decode("utf-8")),

        **kafka_auth_kwargs(),

    )



    _set_state("starting")

    try:

        await with_retry(consumer.start, name="Kafka consumer")

        _set_state("running")

        logger.info(f"Kafka consumer started, listening on: {CONSUME_TOPICS}")



        async for msg in consumer:

            event = msg.value if isinstance(msg.value, dict) else {}

            correlation_id = event.get("correlation_id")

            if correlation_id:

                CorrelationContext.set(correlation_id)

            # Dedupe (event_inbox), retry with backoff, then event_dlq.

            await deliver(

                async_session_factory, CONSUMER_NAME, msg.topic, event,

                lambda event=event, topic=msg.topic: dispatch(topic, event),

            )



    except asyncio.CancelledError:

        _set_state("stopped", "cancelled")

        logger.info("Kafka consumer loop cancelled")

    except Exception as e:

        _set_state("stopped", f"{type(e).__name__}: {e}")

        logger.error(f"Kafka consumer stopped: {e}", exc_info=True)

    finally:

        if CONSUMER_STATE["status"] != "stopped":

            _set_state("stopped", "consumer loop ended")

        await consumer.stop()

        logger.info("Kafka consumer stopped")





async def _handle_document_classified(db, payload: dict):

    # Only actionable when the extraction needs a human to look at it —

    # otherwise every successfully auto-classified document would fire an

    # email, which isn't useful signal.

    if not payload.get("needs_review"):

        return

    recipient = await directory.resolve_recipient(db, None)

    await dispatcher.notify(

        db,

        event_type="document.classified",

        template_name="document_classified",

        context=payload,

        recipient=recipient,

        related_entity_id=payload.get("document_id"),

    )





async def _handle_license_usage_updated(db, payload: dict):

    recipient = await directory.resolve_recipient(db, None)

    await dispatcher.notify(

        db,

        event_type="license.usage.updated",

        template_name="license_usage_updated",

        context=payload,

        recipient=recipient,

        related_entity_id=payload.get("license_id"),

    )





async def _send_approval_request(db, payload: dict, level: Optional[str], step_index: int):

    """Asks the people holding `level` to decide, each with the portal link

    and (when available) a one-click action link."""

    request_id = payload.get("request_id")

    recipients = await directory.approvers_for_level(db, level, payload.get("amount"))

    if not recipients:

        recipients = [await directory.resolve_recipient(db, level)]



    # Prompt 8 B1: Mint email action URL at render time

    action_url, action_expires_at = await _mint_action_url(

        request_id=request_id,

        approver_id=level or recipients[0],

        step_index=step_index,

    )



    context = dict(payload)

    if action_url:

        context["action_url"] = action_url

        context["action_expires_at"] = action_expires_at

    else:

        context["action_url"] = None



    public_base_url = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8080").rstrip("/")

    context["portal_url"] = f"{public_base_url}/app/requests/{request_id}?step=approval"



    for recipient in recipients:

        await dispatcher.notify(

            db,

            event_type="approval.requested",

            template_name="approval_requested",

            context=context,

            recipient=recipient,

            related_entity_id=request_id,

        )





async def _handle_approval_requested(db, payload: dict):

    chain = payload.get("approval_chain") or []

    step_index = int(payload.get("step_index", 0))

    level = chain[step_index] if step_index < len(chain) else (chain[0] if chain else None)

    await _send_approval_request(db, payload, level, step_index)

    if step_index == 0 and payload.get("requested_by"):

        requester_email = await directory.resolve_recipient(db, payload.get("requested_by"))

        public_base_url = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8080").rstrip("/")

        user_context = {

            **payload,

            "portal_url": f"{public_base_url}/app/requests/{payload.get('request_id')}",

        }

        await dispatcher.notify(

            db,

            event_type="approval.requested",

            template_name="request_submitted",

            context=user_context,

            recipient=requester_email,

            related_entity_id=payload.get("request_id"),

        )





async def _ask_next_level(db, payload: dict, escalated: bool = False) -> None:

    """approval.decided is published per level; after an approval with

    levels left, the next level's approvers are asked to decide. Also used

    when a level misses its SLA and the workflow escalates (escalated=True)."""

    if payload.get("decision") != "approved" and not escalated:

        return

    chain, amount = await directory.approval_chain(db, payload.get("request_id"))

    level = str(payload.get("decision_level") or "")  # "level_<n>_<approver level>"

    parts = level.split("_", 2)

    if len(parts) < 3 or parts[0] != "level" or not parts[1].isdigit():

        return

    next_index = int(parts[1])  # levels are 1-based, so this is the next one

    if next_index >= len(chain):

        return

    row = (await db.execute(text(

        "SELECT requested_by, department, currency, request_type, spend_tier, sla_deadline "

        "FROM purchase_requests WHERE id = CAST(:r AS uuid)"

    ), {"r": payload["request_id"]})).first()

    if row is None:

        return

    await _send_approval_request(db, {

        "request_id": payload["request_id"], "requested_by": row.requested_by, "department": row.department,

        "amount": amount, "currency": row.currency or "INR", "request_type": row.request_type,

        "spend_tier": row.spend_tier, "sla_deadline": _when(row.sla_deadline.isoformat()) if row.sla_deadline else "",

        "approval_chain": chain, "step_index": next_index,

        "escalated_from": chain[next_index - 1] if escalated else "",

    }, chain[next_index], next_index)





async def _handle_reminder_due(db, payload: dict):

    """An approval, signature, bank-detail check or review waiting too long

    (shared/reminders.py): remind the people who can act on it."""

    link = payload.get("link") or "/app"

    context = {**payload, "item_url": _portal(link), "waiting_hours": round(float(payload.get("waiting_hours") or 0), 1),

               "detail": payload.get("detail") or ""}

    for recipient in await directory.reminder_recipients(db, payload):

        await dispatcher.notify(

            db,

            event_type="reminder.due",

            template_name="reminder_due",

            context=context,

            recipient=recipient,

            related_entity_id=payload.get("entity_id"),

            priority_override=routing.URGENT,

        )





async def _handle_approval_decided(db, payload: dict):

    # approval.decided's payload has no requester contact field, only

    # request_id — look the requester up via the shared purchase_requests

    # table (see app/services/directory.py). The `escalated` flag is

    # surfaced in the rendered email body (app/templates/approval_decided.j2).

    requester = await directory.requester_for_request_id(db, payload.get("request_id"))

    recipient = await directory.resolve_recipient(db, requester)

    await dispatcher.notify(

        db,

        event_type="approval.decided",

        template_name="approval_decided",

        context=payload,

        recipient=recipient,

        related_entity_id=payload.get("request_id"),

    )

    await _ask_next_level(db, payload)



    # Notify vendor when outcome is reached (final approval or rejection)

    decision = payload.get("decision")

    chain, _ = await directory.approval_chain(db, payload.get("request_id"))

    level = str(payload.get("decision_level") or "")

    parts = level.split("_", 2)

    is_final = False

    if decision == "rejected":

        is_final = True

    elif decision == "approved":

        if len(parts) >= 2 and parts[1].isdigit():

            current_idx = int(parts[1])

            if current_idx >= len(chain):

                is_final = True

        elif not chain:

            is_final = True



    # Prompt 10 Section 6.5: vendors must NEVER be notified of internal approvals (only rejections)
    if is_final and decision == "rejected":
        vendor_id = await directory.vendor_for_request(db, payload.get("request_id"))
        if vendor_id:
            vendor_contact = await directory.vendor_contact(db, vendor_id)
            if vendor_contact:
                vendor_name = await directory.vendor_name(db, vendor_id)
                await dispatcher.notify(
                    db,
                    event_type="approval.decided",
                    template_name="approval_decided_vendor",
                    context={
                        **payload,
                        "vendor_name": vendor_name,
                        "comments": payload.get("comments") or "No comments provided",
                    },
                    recipient=vendor_contact,
                    related_entity_id=payload.get("request_id"),
                )





async def _handle_contract_generated(db, payload: dict):

    requester = await directory.requester_for_request_id(db, payload.get("purchase_request_id"))

    recipient = await directory.resolve_recipient(db, requester)

    await dispatcher.notify(

        db,

        event_type="contract.generated",

        template_name="contract_generated",

        context=payload,

        recipient=recipient,

        related_entity_id=payload.get("contract_id"),

    )





async def _handle_contract_signed(db, payload: dict):

    requester = await directory.requester_for_contract_id(db, payload.get("contract_id"))

    recipient = await directory.resolve_recipient(db, requester)

    await dispatcher.notify(

        db,

        event_type="contract.signed",

        template_name="contract_signed",

        context=payload,

        recipient=recipient,

        related_entity_id=payload.get("contract_id"),

    )

    # The vendor hears it too (contact e-mail, else a placeholder address).

    vendor_id = await directory.vendor_for_contract(db, payload.get("contract_id"))

    if vendor_id:

        await dispatcher.notify(

            db,

            event_type="contract.signed",

            template_name="contract_signed_vendor",

            context={**payload, "vendor_name": await directory.vendor_name(db, vendor_id) or "Supplier",

                     "signed_at": _when(payload.get("signed_at")) or payload.get("signed_at")},

            recipient=await directory.vendor_contact(db, vendor_id),

            related_entity_id=payload.get("contract_id"),

        )





async def _handle_contract_renewal_due(db, payload: dict):

    requester = await directory.requester_for_contract_id(db, payload.get("contract_id"))

    recipient = await directory.resolve_recipient(db, requester)

    await dispatcher.notify(

        db,

        event_type="contract.renewal.due",

        template_name="contract_renewal_due",

        context=payload,

        recipient=recipient,

        related_entity_id=payload.get("contract_id"),

    )





async def _handle_risk_score_updated(db, payload: dict):

    recipient = await directory.resolve_recipient(db, None)

    await dispatcher.notify(

        db,

        event_type="risk.score.updated",

        template_name="risk_score_updated",

        context=payload,

        recipient=recipient,

        related_entity_id=payload.get("vendor_id"),

    )





async def _handle_vendor_offboarded(db, payload: dict):

    recipient = await directory.resolve_recipient(db, None)

    await dispatcher.notify(

        db,

        event_type="vendor.offboarded",

        template_name="vendor_offboarded",

        context=payload,

        recipient=recipient,

        related_entity_id=payload.get("vendor_id"),

    )





async def _handle_vendor_payment_details_flagged(db, payload: dict):

    """Fraud-prevention alert: a vendor's bank/payment details have been

    changed. Per the prompt this is ALWAYS urgent (never digest) —

    finance needs to verify through out-of-band channels before any

    payments go through the updated details."""

    recipient = await directory.resolve_recipient(db, None)

    await dispatcher.notify(

        db,

        event_type="vendor.payment_details_flagged",

        template_name="vendor_payment_details_flagged",

        context=payload,

        recipient=recipient,

        related_entity_id=payload.get("vendor_id"),

    )





async def _handle_notification_send(db, payload: dict):

    """Generic fallback: any service can ask us to render+send an

    arbitrary template with arbitrary context. `priority` is authoritative

    here (urgent vs digest) — see app/services/routing.py."""

    raw_recipient = payload.get("recipient")

    recipient = directory.as_email(raw_recipient) if raw_recipient else await directory.resolve_recipient(db, None)

    # No `or "generic_fallback"` default here on purpose: that string is

    # also a real template filename, so a missing template_name would

    # take the "template_exists" branch below with an unwrapped context,

    # instead of the fallback-wrapper branch that actually supplies the

    # `template_name`/`context` variables generic_fallback.j2 expects.

    requested_template = payload.get("template_name")

    template_context = payload.get("template_context") or {}



    if requested_template == "sla_breach_escalation":

        # The approval workflow escalated past a level that missed its SLA

        # (its notification names that level, not a person): ask the next

        # level's people to decide, as after an approval.

        await _ask_next_level(db, {"request_id": template_context.get("request_id"),

                                   "decision_level": template_context.get("decision_level")}, escalated=True)

        return



    if requested_template and await template_store.exists(db, requested_template):

        template_name = requested_template

        context = dict(template_context)

        # Links into the app for templates about a contract.

        if context.get("contract_id"):

            context.setdefault("contract_url", _portal(f"/app/contracts/{context['contract_id']}"))

            context.setdefault("sign_url", _portal(f"/app/contracts/{context['contract_id']}?action=sign"))

    else:

        template_name = "generic_fallback"

        context = {"template_name": requested_template or "(none specified)", "context": template_context}



    priority = routing.decide_priority("notification.send", payload)



    await dispatcher.notify(

        db,

        event_type="notification.send",

        template_name=template_name,

        context=context,

        recipient=recipient,

        related_entity_id=payload.get("related_entity_id"),

        priority_override=priority,

    )





def _when(iso) -> str | None:

    """'2026-10-25T17:00:00+00:00' -> '25 Oct 2026, 17:00 UTC' for e-mail text."""

    from datetime import datetime, timezone

    try:

        return datetime.fromisoformat(str(iso)).astimezone(timezone.utc).strftime("%d %b %Y, %H:%M UTC")

    except (TypeError, ValueError):

        return None





def _portal(path: str) -> str:

    return f"{os.environ.get('PUBLIC_BASE_URL', 'http://localhost:8080').rstrip('/')}{path}"





async def _handle_budget_threshold_crossed(db, payload: dict):

    """To the budget's owner, or the finance mailbox when it has none."""

    owner = await directory.budget_owner(db, payload.get("budget_id"))

    recipient = await directory.resolve_recipient(db, owner or directory.FINANCE_MAILBOX)

    await dispatcher.notify(

        db, event_type="budget.threshold_crossed", template_name="budget_threshold_crossed",

        context={**payload, "portal_url": _portal(f"/app/budgets/{payload.get('budget_id')}")},

        recipient=recipient, related_entity_id=payload.get("budget_id"),

    )





async def _handle_contract_obligation_due(db, payload: dict):

    """To the obligation's owner; else the requester of the contract's

    purchase request; else the default ops mailbox."""

    owner = payload.get("owner_email") or await directory.requester_for_contract_id(db, payload.get("contract_id"))

    recipient = await directory.resolve_recipient(db, owner)

    context = {"due_date": None, "days_left": None, "detail": "", **payload,

               "portal_url": _portal(f"/app/contracts/{payload.get('contract_id')}")}

    await dispatcher.notify(

        db, event_type="contract.obligation.due", template_name="contract_obligation_due",

        context=context, recipient=recipient, related_entity_id=payload.get("obligation_id"),

    )





async def _handle_rfq_issued(db, payload: dict):

    """One invitation per invited vendor, to its contact e-mail (or a

    placeholder vendor address when it has none)."""

    items = await directory.rfq_items(db, payload.get("rfq_id"))

    for vendor_id in payload.get("vendor_ids") or []:

        recipient = await directory.vendor_contact(db, vendor_id)

        await dispatcher.notify(

            db, event_type="rfq.issued", template_name="rfq_invitation",

            context={**payload, "items": items, "vendor_name": await directory.vendor_name(db, vendor_id),

                     "deadline_text": _when(payload.get("deadline"))},

            recipient=recipient, related_entity_id=payload.get("rfq_id"),

        )





async def _handle_rfq_awarded(db, payload: dict):

    """The award to the winner and a thank-you to everyone else invited."""

    winner = payload.get("vendor_id")

    await dispatcher.notify(

        db, event_type="rfq.awarded", template_name="rfq_awarded",

        context={**payload, "vendor_name": await directory.vendor_name(db, winner)},

        recipient=await directory.vendor_contact(db, winner), related_entity_id=payload.get("rfq_id"),

    )

    for vendor_id in payload.get("losing_vendor_ids") or []:

        await dispatcher.notify(

            db, event_type="rfq.awarded", template_name="rfq_not_selected",

            context={**payload, "vendor_name": await directory.vendor_name(db, vendor_id)},

            recipient=await directory.vendor_contact(db, vendor_id), related_entity_id=payload.get("rfq_id"),

        )





async def _handle_goods_received(db, payload: dict):

    requester = await directory.requester_for_request_id(db, payload.get("request_id"))

    recipient = await directory.resolve_recipient(db, requester)

    await dispatcher.notify(

        db, event_type="goods.received", template_name="goods_received",

        context={**payload, "portal_url": _portal(f"/app/requests/{payload.get('request_id')}"),

                 "received_at_text": _when(payload.get("received_at"))},

        recipient=recipient, related_entity_id=payload.get("request_id"),

    )





_HANDLERS = {

    "budget.threshold_crossed": _handle_budget_threshold_crossed,

    "contract.obligation.due": _handle_contract_obligation_due,

    "rfq.issued": _handle_rfq_issued,

    "rfq.awarded": _handle_rfq_awarded,

    "goods.received": _handle_goods_received,

    "document.classified": _handle_document_classified,

    "vendor.payment_details_flagged": _handle_vendor_payment_details_flagged,

    "license.usage.updated": _handle_license_usage_updated,

    "approval.requested": _handle_approval_requested,

    "approval.decided": _handle_approval_decided,

    "reminder.due": _handle_reminder_due,

    "contract.generated": _handle_contract_generated,

    "contract.signed": _handle_contract_signed,

    "contract.renewal.due": _handle_contract_renewal_due,

    "risk.score.updated": _handle_risk_score_updated,

    "vendor.offboarded": _handle_vendor_offboarded,

    "notification.send": _handle_notification_send,

}

