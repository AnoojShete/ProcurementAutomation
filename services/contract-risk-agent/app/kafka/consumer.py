"""Kafka consumer for the Contract & Risk Analysis Agent.

Consumes vendor.matched (document-vendor-agent) and approval.decided
(approval-inventory-agent) per shared/schemas/events.md's "Consumed by"
column for this service.
"""
import json
import asyncio
import logging
from datetime import datetime, timezone

from aiokafka import AIOKafkaConsumer
from shared.kafka_security import kafka_auth_kwargs
from app.config import settings
from app.database import async_session_factory
from app.services.contract_service import (
    ContractGenerationError, auto_send_for_signature, generate_contract_for_request,
)
from app.models import Contract, SigningMandate
from sqlalchemy import select, text
from shared.eventing import deliver, PermanentEventError
from shared.rules_engine import get_rule
from app.services.risk_service import score_vendor

from shared.infra.retry import with_retry
from shared.logging.context import CorrelationContext

logger = logging.getLogger(__name__)

CONSUMER_NAME = "contract-risk-agent"

CONSUME_TOPICS = [
    "vendor.matched",     # published by document-vendor-agent
    "approval.decided",   # published by approval-inventory-agent
    "business_rule.updated", # published by auth-service
]


async def start_consumer(app):
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

    try:
        await with_retry(consumer.start, name="Kafka consumer")
        logger.info(f"Kafka consumer started, listening on: {CONSUME_TOPICS}")

        async for msg in consumer:
            event = msg.value
            correlation_id = event.get("correlation_id")
            if correlation_id:
                CorrelationContext.set(correlation_id)
            # Retries, then dead-letters to event_dlq instead of dropping it.
            await deliver(
                async_session_factory, CONSUMER_NAME, msg.topic, event,
                lambda event=event, topic=msg.topic: dispatch(app, topic, event),
            )

    except asyncio.CancelledError:
        logger.info("Kafka consumer loop cancelled")
    finally:
        await consumer.stop()
        logger.info("Kafka consumer stopped")


async def dispatch(app, topic: str, event: dict) -> None:
    """Routes one event; raises on failure so deliver() retries or
    dead-letters it. Also used to replay DLQ entries."""
    event_type = event.get("event_type")
    payload = event.get("payload", {})
    if event_type == "vendor.matched":
        await _handle_vendor_matched(app, payload)
    elif event_type == "approval.decided":
        await _handle_approval_decided(app, payload)
    elif event_type == "business_rule.updated":
        rule_key = payload.get("rule_key")
        if rule_key:
            from shared.rules_engine import invalidate_rule
            invalidate_rule(rule_key)
            logger.info(f"Invalidated local rules_engine cache for key: {rule_key}")
    else:
        logger.warning(f"Unknown event type on topic {topic}: {event_type}")


async def _handle_vendor_matched(app, payload: dict):
    """A newly-matched vendor gets an initial risk score so the frontend
    has something to show as soon as the vendor exists."""
    if payload.get("match_type") != "new":
        return
    vendor_id = payload.get("vendor_id")
    logger.info(f"New vendor matched, scoring: vendor_id={vendor_id}")
    async with async_session_factory() as db:
        await score_vendor(db, app.state.kafka_producer, vendor_id)


def is_final_approval(decision_level: str | None, approval_chain: list | None) -> bool:
    """approval.decided is published once per approval level
    ("level_<n>_<level>"); only the last level's approval (or an
    auto-approval) means the request is approved."""
    parts = str(decision_level or "").split("_", 2)
    if len(parts) < 3 or parts[0] != "level" or not parts[1].isdigit():
        return True  # "auto" or an older format: a single, final decision
    return int(parts[1]) >= len(approval_chain or [])


async def _handle_approval_decided(app, payload: dict):
    """An approved purchase request is ready for a contract. Idempotent: a
    redelivered approval.decided must not produce a second contract."""
    if payload.get("decision") != "approved":
        return
    request_id = payload.get("request_id")
    async with async_session_factory() as db:
        chain = (await db.execute(
            text("SELECT approval_chain FROM purchase_requests WHERE id = CAST(:r AS uuid)"), {"r": request_id}
        )).scalar_one_or_none()
        if not is_final_approval(payload.get("decision_level"), chain):
            logger.info(f"Request {request_id} approved at {payload.get('decision_level')}; "
                        f"waiting for the remaining levels before generating a contract")
            return
        contract = (
            await db.execute(select(Contract).where(Contract.purchase_request_id == request_id).limit(1))
        ).scalar_one_or_none()
        if contract is not None:
            logger.info(f"Request {request_id} already has contract {contract.id}; skipping generation")
        else:
            logger.info(f"Request approved, generating contract: request_id={request_id}")
            try:
                contract = await generate_contract_for_request(db, app.state.kafka_producer, request_id, template_name=None)
            except ContractGenerationError as e:
                # e.g. the request doesn't exist — retrying can't fix it.
                raise PermanentEventError(str(e)) from e
        # Send for signature once, automatically (every approved request,
        # or drop-folder quotes only: rule contract.auto_send_scope).
        # Also runs for an existing contract, so a crash between generating
        # and sending is finished on redelivery.
        # Prompt 10 Section 2.2: Auto-sign under standing finance mandate
        channel = payload.get("decision_channel") or "portal"
        decided_by = payload.get("decided_by") or ""
        decision_level = payload.get("decision_level") or ""
        bulk_batch_id = payload.get("bulk_batch_id")
        is_finance = "finance" in decision_level.lower()

        auto_sign_enabled = get_rule("contract.auto_sign_enabled", fallback=False)
        allow_email = get_rule("contract.auto_sign_allow_email_channel", fallback=True)

        if contract.status != "signed" and auto_sign_enabled and is_finance and (bulk_batch_id or channel in ("bulk", "email")):
            channel_allowed = (channel == "portal") or (channel in ("email", "bulk") and allow_email)
            if not channel_allowed:
                logger.info(f"Auto-signing skipped for contract {contract.id}: channel {channel} not permitted")
            else:
                now_utc = datetime.now(timezone.utc)
                stmt_mandate = select(SigningMandate).where(
                    SigningMandate.user_id == decided_by,
                    SigningMandate.status == "active",
                    SigningMandate.valid_until > now_utc,
                )
                mandate_res = await db.execute(stmt_mandate)
                mandate = mandate_res.scalars().first()
                if not mandate:
                    logger.info(f"Auto-signing skipped for contract {contract.id}: no active signing mandate for {decided_by}")
                else:
                    from app.services.contract_service import _contract_amount, signing_risk, sign_contract_digitally
                    spend_amount = await _contract_amount(db, contract) or 0.0
                    max_auto_amount = float(get_rule("contract.auto_sign_max_amount", fallback=25000.0))
                    allowed_cap = min(float(mandate.max_amount_per_contract), max_auto_amount)
                    if spend_amount > allowed_cap:
                        logger.info(f"Auto-signing skipped for contract {contract.id}: spend {spend_amount} exceeds cap {allowed_cap}")
                    else:
                        risk = await signing_risk(db, contract.vendor_id, spend_amount=spend_amount)
                        if risk.get("signing_blocked"):
                            logger.info(f"Auto-signing skipped for contract {contract.id}: vendor blocked ({risk.get('blocked_reason')})")
                        else:
                            mandate_short = str(mandate.id)[:8]
                            batch_short = str(bulk_batch_id)[:8] if bulk_batch_id else "batch"
                            channel_text = "Approved through email link" if channel == "email" else "Approved in the application"
                            wording = f"{channel_text} · Approved and signed under signing mandate {mandate_short} (batch {batch_short})"
                            signer_name = decided_by.split("@")[0].replace(".", " ").replace("_", " ").title() if decided_by else "Head of Finance"
                            try:
                                contract, cert = await sign_contract_digitally(
                                    db=db,
                                    kafka_producer=app.state.kafka_producer,
                                    contract_id=contract.id,
                                    signer_name=signer_name,
                                    signer_email=decided_by or "finance@company.com",
                                    signature_data=None,
                                    legal_consent=True,
                                    signer_designation="Head of Finance",
                                    signing_method=wording,
                                    approval_channel=channel,
                                    mandate_id=mandate.id,
                                    bulk_batch_id=bulk_batch_id,
                                    mandate_sha256=mandate.mandate_text_sha256,
                                    ip_address="Automated Mandate Engine",
                                    user_agent="Approval-To-Contract Bridge",
                                    risk_acknowledged=True,
                                )
                                logger.info(f"Contract {contract.id} automatically signed under mandate {mandate.id}")
                            except Exception as e:
                                logger.warning(f"Could not auto-sign contract {contract.id}: {e}")

        contract_id = contract.id
        outcome = await auto_send_for_signature(db, app.state.kafka_producer, contract)
        if outcome not in ("skipped", "not_from_drop_folder", "already_tried"):
            logger.info(f"Contract {contract_id} auto-send: {outcome}")
