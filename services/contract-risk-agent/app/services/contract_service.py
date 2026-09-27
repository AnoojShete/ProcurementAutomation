import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import load_config
from app.models import AuditLog, Contract, PurchaseRequest, Vendor
from app.services.clause_extraction import extract_clauses
from app.services.contract_pdf import AuditEntry, ContractPdfInput, _title_case, render_contract_pdf
from app.services.esign_client import EsignProviderError, download_signed_pdf, request_signature
from app.services.audit import write_audit_log
from app.services.temporal_client import start_renewal_workflow
from app.metrics import contract_generation_total
from shared.eventing import staged

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

    from app.services.clause_router import route_clause_extraction
    router_result = await route_clause_extraction(db, contract_id, contract_text)
    clauses = router_result.clauses.copy() if isinstance(router_result.clauses, dict) else router_result.clauses.__dict__

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
    # Events go into the outbox in the same transaction as the contract, so
    # a crash after commit can't lose them (shared/eventing/outbox.py).
    outbox = staged(kafka_producer, db)
    if outbox is not None:
        await outbox.publish_contract_generated(
            contract,
            model_used=router_result.model_used,
            fallback_triggered=router_result.fallback_triggered
        )
        if pr.vendor_id:
            await outbox.publish_notification(
                recipient=pr.requested_by,
                channel="email",
                template_name="contract_ready_for_signature",
                template_context={"contract_id": contract_id, "vendor_name": vendor_name},
                priority="digest",
                related_entity_id=contract_id,
            )
    await db.commit()
    await db.refresh(contract)
    contract_generation_total.labels(status="generated").inc()

    await start_renewal_workflow(contract_id)
    return contract


async def send_for_signature(
    db: AsyncSession, kafka_producer, contract_id: str, signer_email: Optional[str], provider: str = "documenso"
) -> Contract:
    contract = await db.get(Contract, contract_id)
    if contract is None:
        raise ContractGenerationError(f"contract {contract_id} not found")
    if contract.status != "draft":
        raise ContractGenerationError(f"contract {contract_id} is not in draft status")

    pdf_input = await build_pdf_input(db, contract)
    try:
        provider_ref = await request_signature(
            contract_id, signer_email, provider=provider,
            pdf=render_contract_pdf(pdf_input), title=f"{_agreement_title(contract)} — {pdf_input.vendor_name}",
        )
    except EsignProviderError as e:
        raise ContractGenerationError(str(e)) from e
    contract.status = "pending_signature"
    contract.esign_provider_ref = provider_ref
    contract.updated_at = datetime.now(timezone.utc)

    await write_audit_log(
        db, "contract", contract_id, "sent_for_signature",
        {"esign_provider_ref": provider_ref, "signer_email": signer_email, "provider": provider},
    )
    await db.commit()
    await db.refresh(contract)
    return contract


async def sign_contract_simulated(db: AsyncSession, kafka_producer, contract_id: str, signed_by: Optional[str] = None) -> Contract:
    contract = await db.get(Contract, contract_id)
    if contract is None:
        raise ContractGenerationError(f"contract {contract_id} not found")
    if contract.status == "signed":
        return contract
    if signed_by is None:
        # Whoever the contract was sent to, so the signed copy names them.
        sent = await _latest_audit_payload(db, contract_id, "sent_for_signature")
        signed_by = (sent or {}).get("signer_email") or "authorized_signer@company.com"

    now = datetime.now(timezone.utc)
    contract.status = "signed"
    contract.signed_at = now
    contract.signed_by = signed_by
    contract.updated_at = now

    await write_audit_log(
        db, "contract", contract_id, "signed",
        {"simulated": True, "signed_by": signed_by, "esign_provider_ref": contract.esign_provider_ref},
    )
    outbox = staged(kafka_producer, db)
    if outbox is not None:
        await outbox.publish_contract_signed(contract)
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


class ContractNotSignedError(Exception):
    pass


def _agreement_title(contract: Contract) -> str:
    for line in (contract.contract_text or "").splitlines():
        if line.strip():
            return _title_case(line.strip())
    return "Contract"


async def _latest_audit_payload(db: AsyncSession, contract_id: str, action: str) -> Optional[dict]:
    row = (
        await db.execute(
            select(AuditLog)
            .where(AuditLog.entity_type == "contract", AuditLog.entity_id == str(contract_id), AuditLog.action == action)
            .order_by(AuditLog.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return row.payload if row else None


def _audit_detail(action: str, payload: dict) -> str:
    payload = payload or {}
    if action == "generated":
        return f"Template {str(payload.get('template_used', '')).replace('_', ' ')}"
    if action == "sent_for_signature":
        who = payload.get("signer_email") or "signer"
        return f"Sent to {who} via {str(payload.get('provider') or 'provider').title()}"
    if action.startswith("signed"):
        detail = f"Signed by {payload.get('signed_by', 'signer')}"
        return detail + (" (simulated)" if payload.get("simulated") else "")
    return ""


async def build_pdf_input(db: AsyncSession, contract: Contract, include_audit: bool = False) -> ContractPdfInput:
    vendor_name = "Unspecified Vendor"
    if contract.vendor_id:
        vendor = await db.get(Vendor, contract.vendor_id)
        if vendor:
            vendor_name = vendor.name
    trail: list[AuditEntry] = []
    if include_audit:
        rows = (
            await db.execute(
                select(AuditLog)
                .where(AuditLog.entity_type == "contract", AuditLog.entity_id == str(contract.id))
                .order_by(AuditLog.created_at.asc())
            )
        ).scalars().all()
        trail = [AuditEntry(at=r.created_at, action=r.action, detail=_audit_detail(r.action, r.payload)) for r in rows]
    return ContractPdfInput(
        contract_id=str(contract.id),
        contract_text=contract.contract_text or "",
        status=contract.status,
        version=contract.version or 1,
        template=contract.template,
        vendor_name=vendor_name,
        generated_at=contract.generated_at,
        signed_at=contract.signed_at,
        signed_by=contract.signed_by,
        esign_provider_ref=contract.esign_provider_ref,
        audit_trail=trail,
    )


def document_filename(contract: Contract, signed: bool) -> str:
    base = f"contract-{str(contract.id)[:8]}-v{contract.version or 1}"
    return f"{base}-signed.pdf" if signed else f"{base}.pdf"


async def render_document(db: AsyncSession, contract: Contract) -> bytes:
    """The working copy: the agreement as generated, unsigned."""
    return render_contract_pdf(await build_pdf_input(db, contract))


async def render_signed_document(db: AsyncSession, contract: Contract) -> bytes:
    """The executed copy. Documenso's own sealed PDF when it signed the
    contract; otherwise rendered here with a certificate of completion."""
    if contract.status != "signed":
        raise ContractNotSignedError(f"contract {contract.id} is not signed yet")
    provider_pdf = await download_signed_pdf(contract.esign_provider_ref)
    if provider_pdf is not None:
        return provider_pdf
    return render_contract_pdf(await build_pdf_input(db, contract, include_audit=True), include_certificate=True)
