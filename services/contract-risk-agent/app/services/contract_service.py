import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import load_config
from app.models import Contract, PurchaseRequest, Vendor
from app.services.clause_extraction import extract_clauses
from app.services.esign_client import request_signature
from app.services.audit import write_audit_log
from app.services.temporal_client import start_renewal_workflow
from app.metrics import contract_generation_total

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates")
_jinja_env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=select_autoescape(disabled_extensions=("j2",)))

REQUEST_TYPE_TO_TEMPLATE = {
    "hardware": "hardware_purchase",
    "license": "saas_subscription",
    "saas": "saas_subscription",
    "reclaim": "professional_services",
}
DEFAULT_TEMPLATE = "hardware_purchase"


class ContractGenerationError(Exception):
    pass


async def _infer_template_name(db: AsyncSession, purchase_request_id: str) -> str:
    """Best-effort: use purchase_requests.request_type if that column
    exists (it's owned by approval-inventory-agent and may not be migrated
    into the shared schema yet). Falls back to a sane default so contract
    generation never hard-fails on a missing column it doesn't own."""
    try:
        row = (
            await db.execute(
                text("SELECT request_type FROM purchase_requests WHERE id = :id"),
                {"id": purchase_request_id},
            )
        ).first()
        if row and row[0] in REQUEST_TYPE_TO_TEMPLATE:
            return REQUEST_TYPE_TO_TEMPLATE[row[0]]
    except Exception:
        pass
    return DEFAULT_TEMPLATE


def render_contract_text(template_name: str, context: dict) -> str:
    template = _jinja_env.get_template(f"{template_name}.j2")
    return template.render(**context)


async def generate_contract_for_request(
    db: AsyncSession, kafka_producer, purchase_request_id: str, template_name: Optional[str]
) -> Contract:
    pr = await db.get(PurchaseRequest, purchase_request_id)
    if pr is None:
        raise ContractGenerationError(f"purchase_request {purchase_request_id} not found")

    if template_name is None:
        template_name = await _infer_template_name(db, purchase_request_id)
    if template_name not in REQUEST_TYPE_TO_TEMPLATE.values() and template_name != DEFAULT_TEMPLATE:
        raise ContractGenerationError(f"unknown template_name {template_name}")

    vendor_name = "Unspecified Vendor"
    if pr.vendor_id:
        vendor = await db.get(Vendor, pr.vendor_id)
        if vendor:
            vendor_name = vendor.name

    renewal_cfg = load_config().get("renewal", {})
    notice_period_days = renewal_cfg.get("default_notice_period_days", 30)
    contract_end_date = (datetime.now(timezone.utc) + timedelta(days=365)).date()

    contract_id = str(uuid.uuid4())
    generated_at = datetime.now(timezone.utc)

    contract_text = render_contract_text(
        template_name,
        {
            "contract_id": contract_id,
            "generated_at": generated_at.isoformat(),
            "vendor_name": vendor_name,
            "purchase_request_id": purchase_request_id,
            "department": pr.department,
            "items": pr.items or [],
            "amount": pr.amount,
            "currency": pr.currency,
            "contract_end_date": contract_end_date.isoformat(),
            "notice_period_days": notice_period_days,
        },
    )

    # Extract clauses back out of the generated text — same code path used
    # for contracts uploaded/imported from elsewhere, so it's exercised and
    # tested against real prose, not just trusted because we wrote it.
    clauses = extract_clauses(contract_text)

    contract = Contract(
        id=contract_id,
        purchase_request_id=purchase_request_id,
        vendor_id=pr.vendor_id,
        template=template_name,
        version=1,
        status="draft",
        contract_text=contract_text,
        renewal_type=clauses["renewal_type"],
        notice_period_days=clauses["notice_period_days"] or notice_period_days,
        contract_end_date=clauses["contract_end_date"] or contract_end_date,
        generated_at=generated_at,
        created_at=generated_at,
        updated_at=generated_at,
    )
    db.add(contract)
    await write_audit_log(
        db, "contract", contract_id, "generated",
        {"purchase_request_id": purchase_request_id, "template_used": template_name},
    )
    await db.commit()
    await db.refresh(contract)
    contract_generation_total.labels(status="generated").inc()

    await start_renewal_workflow(contract_id)

    if kafka_producer is not None:
        await kafka_producer.publish_contract_generated(contract)
        if pr.vendor_id:
            await kafka_producer.publish_notification(
                recipient=pr.requested_by,
                channel="email",
                template_name="contract_ready_for_signature",
                template_context={"contract_id": contract_id, "vendor_name": vendor_name},
                priority="digest",
                related_entity_id=contract_id,
            )
    return contract


async def send_for_signature(db: AsyncSession, kafka_producer, contract_id: str, signer_email: Optional[str]) -> Contract:
    contract = await db.get(Contract, contract_id)
    if contract is None:
        raise ContractGenerationError(f"contract {contract_id} not found")
    if contract.status != "draft":
        raise ContractGenerationError(f"contract {contract_id} is not in draft status")

    provider_ref = await request_signature(contract_id, signer_email)
    contract.status = "pending_signature"
    contract.esign_provider_ref = provider_ref
    contract.updated_at = datetime.now(timezone.utc)

    await write_audit_log(
        db, "contract", contract_id, "sent_for_signature",
        {"esign_provider_ref": provider_ref, "signer_email": signer_email},
    )
    await db.commit()
    await db.refresh(contract)
    return contract


async def get_contract(db: AsyncSession, contract_id: str) -> Optional[Contract]:
    return await db.get(Contract, contract_id)


async def list_contracts(db: AsyncSession, limit: int = 100) -> list[Contract]:
    """Most-recently-generated first — backs the tracking dashboard."""
    result = await db.execute(
        select(Contract).order_by(Contract.generated_at.desc().nulls_last()).limit(limit)
    )
    return list(result.scalars().all())


async def get_renewals_due(db: AsyncSession, within_days: int) -> list[Contract]:
    cutoff = (datetime.now(timezone.utc) + timedelta(days=within_days)).date()
    result = await db.execute(
        select(Contract).where(
            Contract.contract_end_date.is_not(None),
            Contract.contract_end_date <= cutoff,
            Contract.status.in_(["signed", "pending_signature"]),
        )
    )
    return list(result.scalars().all())
