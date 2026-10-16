import hashlib
import logging
import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import load_config, settings
from app.models import AuditLog, Contract, PurchaseRequest, Vendor
from app.services.clause_extraction import extract_clauses
from app.services.contract_pdf import AuditEntry, ContractPdfInput, _title_case, render_contract_pdf
from app.services.esign_client import EsignProviderError, download_signed_pdf, live_provider_ref, request_signature
from app.services.audit import write_audit_log
from app.services.temporal_client import start_renewal_workflow
from app.metrics import contract_generation_total
from shared.drop_folder import INBOX_UPLOADER
from shared.eventing import staged

logger = logging.getLogger(__name__)

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


class RiskAcknowledgementRequired(ContractGenerationError):
    """Signing for a High-risk (or never-scored) vendor without saying so."""


# BR-6: the signer must explicitly acknowledge these before signing.
ACK_BANDS = ("High",)


async def signing_risk(db: AsyncSession, vendor_id: Optional[str]) -> dict:
    """The vendor's latest risk as the signer should see it: band, score,
    reasons, triggered hard overrides, and whether signing needs an explicit
    acknowledgement (High — overrides always make a vendor High — or not
    scored at all, since an unknown risk is not a low one)."""
    from app.services.risk_service import latest_risk_score
    row = await latest_risk_score(db, vendor_id) if vendor_id else None
    if row is None:
        return {"risk_band": None, "risk_score": None, "reasons": [], "overrides": [], "scored_at": None,
                "acknowledgement_required": True,
                "acknowledgement_reason": ("This vendor has not been risk-scored." if vendor_id
                                           else "No vendor is linked to this contract, so its risk is unknown.")}
    triggered = [o for o in (row.overrides or []) if o.get("status") == "triggered"]
    needs = row.band in ACK_BANDS
    return {
        "risk_band": row.band,
        "risk_score": float(row.score) if row.score is not None else None,
        "reasons": [f for f in (row.details or []) if not f.get("override")],
        "overrides": triggered,
        "scored_at": row.scored_at.isoformat() if row.scored_at else None,
        "acknowledgement_required": needs,
        "acknowledgement_reason": (
            "Hard override: " + "; ".join(o.get("reason") or o["check"] for o in triggered) + "." if needs and triggered
            else "The vendor's risk band is High." if needs else None),
    }


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
    # The notice period and end date were written into this text by us, so
    # those values stay authoritative; the extractor's reading is a check,
    # and a disagreement is recorded in the audit log instead of silently
    # overwriting the contract's real terms. Renewal type comes from the
    # extractor (the template's wording decides it).
    written = {"notice_period_days": notice_period_days, "contract_end_date": contract_end_date}
    clause_mismatches = {
        field: {"written": str(value), "extracted": str(clauses[field])}
        for field, value in written.items()
        if clauses.get(field) is not None and clauses[field] != value
    }

    contract = Contract(
        id=contract_id,
        purchase_request_id=purchase_request_id,
        vendor_id=pr.vendor_id,
        template=template_name,
        version=1,
        status="draft",
        contract_text=contract_text,
        renewal_type=clauses["renewal_type"],
        notice_period_days=notice_period_days,
        contract_end_date=contract_end_date,
        generated_at=generated_at,
        created_at=generated_at,
        updated_at=generated_at,
    )
    db.add(contract)
    await write_audit_log(
        db, "contract", contract_id, "generated",
        {"purchase_request_id": purchase_request_id, "template_used": template_name,
         "clause_model": router_result.model_used, "clause_mismatches": clause_mismatches},
    )
    if clause_mismatches:
        logger.warning(f"Contract {contract_id}: {router_result.model_used} read {clause_mismatches} — kept the written values")
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


async def get_authorized_signatories(db: AsyncSession) -> list[str]:
    """Prompt 8 C3: Resolves authorized signatories from active assignments / staff users."""
    signatories = set()
    try:
        rows = (await db.execute(text("SELECT user_email FROM approver_assignments WHERE active"))).all()
        for r in rows:
            if r[0]:
                signatories.add(r[0].strip().lower())
    except Exception:
        pass

    try:
        rows = (await db.execute(text("SELECT email FROM auth_users WHERE role IN ('admin', 'finance', 'approver') AND is_active"))).all()
        for r in rows:
            if r[0]:
                signatories.add(r[0].strip().lower())
    except Exception:
        pass

    # Defaults for demo/test environments
    for default_email in ("finance@demo.example.com", "admin@demo.example.com", "approver@demo.example.com", "authorized_signer@company.com"):
        signatories.add(default_email)

    return sorted(list(signatories))


async def send_for_signature(
    db: AsyncSession, kafka_producer, contract_id: str, signer_email: Optional[str], provider: str = "builtin",
    signer_name: Optional[str] = None, automatic: bool = False,
) -> Contract:
    contract = await db.get(Contract, contract_id)
    if contract is None:
        raise ContractGenerationError(f"contract {contract_id} not found")
    if contract.status != "draft":
        raise ContractGenerationError(f"contract {contract_id} is not in draft status")

    # Prompt 8 C3: Restrict signer email to authorized signatories
    authorized_signatories = await get_authorized_signatories(db)
    if signer_email:
        clean_email = signer_email.strip().lower()
        if clean_email not in authorized_signatories:
            raise ContractGenerationError(
                f"Signer email '{signer_email}' is not an authorized signatory. "
                f"Authorized signatories: {', '.join(authorized_signatories)}"
            )
        resolved_signer = clean_email
    else:
        resolved_signer = authorized_signatories[0]

    pdf_input = await build_pdf_input(db, contract)
    try:
        provider_ref = await request_signature(
            contract_id, resolved_signer, provider=provider,
            pdf=render_contract_pdf(pdf_input), title=f"{_agreement_title(contract)} — {pdf_input.vendor_name}",
            signer_name=signer_name,
        )
    except EsignProviderError as e:
        raise ContractGenerationError(str(e)) from e
    contract.status = "pending_signature"
    contract.esign_provider_ref = provider_ref
    contract.updated_at = datetime.now(timezone.utc)

    await write_audit_log(
        db, "contract", contract_id, "sent_for_signature",
        {"esign_provider_ref": provider_ref, "signer_email": resolved_signer, "provider": provider,
         "automatic": automatic},
    )

    # Prompt 8 C6: Notify signer via notification.send
    outbox = staged(kafka_producer, db)
    if outbox is not None:
        await outbox.publish_notification(
            recipient=resolved_signer,
            channel="email",
            template_name="contract_ready_for_signature",
            template_context={
                "contract_id": contract_id,
                "vendor_name": pdf_input.vendor_name,
                "provider": provider,
                "provider_ref": provider_ref,
            },
            priority="urgent",
            related_entity_id=contract_id,
        )

    await db.commit()
    await db.refresh(contract)
    return contract



async def is_drop_folder_contract(db: AsyncSession, contract: Contract) -> bool:
    """Whether the contract's request came from a drop-folder quote."""
    if not contract.purchase_request_id:
        return False
    uploader = (await db.execute(text(
        "SELECT d.uploaded_by FROM purchase_requests pr JOIN documents d ON d.id = pr.document_id "
        "WHERE pr.id = :id"
    ), {"id": contract.purchase_request_id})).scalar_one_or_none()
    return uploader == INBOX_UPLOADER


async def was_sent_automatically(db: AsyncSession, contract_id: str) -> bool:
    """Whether the contract went out for signature without anyone clicking
    "Send" (its sent_for_signature audit entry says automatic)."""
    payload = (await db.execute(
        select(AuditLog.payload).where(AuditLog.entity_id == contract_id, AuditLog.action == "sent_for_signature")
        .order_by(AuditLog.created_at).limit(1)
    )).scalar_one_or_none()
    return bool((payload or {}).get("automatic"))


def auto_send_scope() -> str:
    """Business rule contract.auto_send_scope: "all" approved requests
    (default) or only "drop_folder" quotes."""
    from shared.rules_engine import get_rule
    scope = get_rule("contract.auto_send_scope", fallback="all")
    return scope if scope in ("all", "drop_folder") else "all"


async def auto_send_for_signature(db: AsyncSession, kafka_producer, contract: Contract) -> str:
    """After approval: send the freshly generated contract for signature
    once, with no clicks. Returns what happened. Applies to every approved
    request, or only drop-folder quotes (rule contract.auto_send_scope).

    Once: only a draft that has never been sent or tried is sent, so a
    redelivered approval.decided never emails the signer twice. A send
    that fails (DocuSign down, no signer email) is recorded on the contract
    and left in draft for someone to send from its page.
    """
    if not settings.esign_auto_send or contract.status != "draft":
        return "skipped"
    contract_id = contract.id  # usable after a rollback expires `contract`
    if auto_send_scope() == "drop_folder" and not await is_drop_folder_contract(db, contract):
        return "not_from_drop_folder"
    tried = (await db.execute(
        select(AuditLog.id).where(
            AuditLog.entity_id == contract_id,
            AuditLog.action.in_(["sent_for_signature", "auto_send_skipped", "auto_send_failed"]),
        ).limit(1)
    )).first()
    if tried:
        return "already_tried"

    # Built-in e-sign with no configured signer: send_for_signature picks
    # one of the platform's authorised signatories, who signs in the app.
    # External providers email someone, so they need an address.
    signer_email = settings.esign_auto_signer_email
    builtin = (settings.esign_auto_provider or "").lower() == "builtin"
    if not signer_email and not builtin:
        if contract.vendor_id:
            signer_email = (await db.execute(
                text("SELECT contact_email FROM vendors WHERE id = :id"), {"id": contract.vendor_id}
            )).scalar_one_or_none()
        if not signer_email:
            await write_audit_log(db, "contract", contract_id, "auto_send_skipped", {
                "reason": "no signer email (set APP_ESIGN_AUTO_SIGNER_EMAIL or the vendor's contact email)",
            })
            await db.commit()
            return "no_signer"

    try:
        await send_for_signature(
            db, kafka_producer, contract_id, signer_email, provider=settings.esign_auto_provider,
            signer_name=settings.esign_auto_signer_name, automatic=True,
        )
    except ContractGenerationError as e:
        await db.rollback()
        await write_audit_log(db, "contract", contract_id, "auto_send_failed", {"reason": str(e)[:300]})
        await db.commit()
        return "failed"
    return "sent"


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


async def sign_contract_digitally(
    db: AsyncSession,
    kafka_producer,
    contract_id: str,
    signer_name: str,
    signer_email: str,
    signature_data: Optional[str] = None,
    legal_consent: bool = False,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    signer_designation: Optional[str] = None,
    risk_acknowledged: bool = False,
) -> tuple[Contract, dict]:
    """Built-in e-sign: the signed-in user signs inside the platform.

    BR-6: for a High-risk or never-scored vendor the signer must pass
    risk_acknowledged=True; the risk they saw is kept in the certificate.

    signer_email must be the caller's authenticated identity (the API passes
    the JWT email). The certificate records who signed, when, from where, the
    consent, the drawn/typed signature, and a SHA-256 over the contract text
    and those details — so any later change to the text or the record is
    detectable by recomputing it. It is an unkeyed hash, not a cryptographic
    signature: it proves integrity only as far as the audit log is trusted."""
    contract = await db.get(Contract, contract_id)
    if contract is None:
        raise ContractGenerationError(f"contract {contract_id} not found")
    if not legal_consent:
        raise ContractGenerationError("Consent to sign electronically is required.")
    if contract.status == "signed":
        cert = await get_signature_certificate(db, contract_id)
        return contract, cert or {}
    if contract.status not in ("draft", "pending_signature"):
        raise ContractGenerationError(f"contract {contract_id} can't be signed in status {contract.status!r}")
    provider_name = live_provider_ref(contract.esign_provider_ref)
    if provider_name:
        raise ContractGenerationError(f"this contract is out for signature in {provider_name}; it completes there")
    risk = await signing_risk(db, contract.vendor_id)
    if risk["acknowledgement_required"] and not risk_acknowledged:
        raise RiskAcknowledgementRequired(
            f"{risk['acknowledgement_reason']} Acknowledge the vendor's risk before signing.")

    now = datetime.now(timezone.utc)
    payload_to_seal = f"{contract_id}|{contract.contract_text or ''}|{signer_name}|{signer_email}|{signer_designation or ''}|{now.isoformat()}|{signature_data or ''}"
    sha256_seal = hashlib.sha256(payload_to_seal.encode("utf-8")).hexdigest()

    contract.status = "signed"
    contract.signed_at = now
    contract.signed_by = f"{signer_name} <{signer_email}>"
    contract.esign_provider_ref = f"builtin-seal-{sha256_seal[:16]}"
    contract.updated_at = now

    certificate = {
        "certificate_id": str(uuid.uuid4()),
        "contract_id": contract_id,
        "template_used": contract.template,
        "signer_name": signer_name,
        "signer_email": signer_email,
        "signer_designation": signer_designation,
        "signed_at": now.isoformat(),
        "signature_seal": sha256_seal,
        "legal_framework": "ESIGN Act (15 U.S.C. § 7001) / UETA",
        "consent_acknowledged": True,
        "ip_address": ip_address,
        "user_agent": user_agent,
        "signature_image": signature_data,
        "vendor_risk_at_signing": {
            "risk_band": risk["risk_band"], "risk_score": risk["risk_score"],
            "overrides": [o["check"] for o in risk["overrides"]],
            "acknowledgement_required": risk["acknowledgement_required"],
            "acknowledged": bool(risk_acknowledged and risk["acknowledgement_required"]),
        },
    }
    await write_audit_log(db, "contract", contract_id, "digitally_signed", certificate)
    # Same transaction as the status change (shared/eventing/outbox.py).
    outbox = staged(kafka_producer, db)
    if outbox is not None:
        await outbox.publish_contract_signed(contract)
    await db.commit()
    await db.refresh(contract)
    return contract, certificate


async def get_signature_certificate(db: AsyncSession, contract_id: str) -> Optional[dict]:
    """The built-in e-sign certificate from the audit log, or None when the
    contract wasn't signed with the built-in e-sign (Documenso's and the
    webhook's own records are in the signed copy's certificate of completion)."""
    result = await db.execute(
        select(AuditLog)
        .where(AuditLog.entity_id == contract_id, AuditLog.action == "digitally_signed")
        .order_by(AuditLog.created_at.desc())
        .limit(1)
    )
    log_entry = result.scalars().first()
    if log_entry and isinstance(log_entry.payload, dict):
        return log_entry.payload
    return None


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
    if action == "digitally_signed":
        desig_str = f" ({payload.get('signer_designation')})" if payload.get('signer_designation') else ""
        return f"Signed in the platform by {payload.get('signer_name', 'signer')}{desig_str} <{payload.get('signer_email', '')}>, seal {str(payload.get('signature_seal', ''))[:16]}"
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

    signature_image = None
    signer_designation = None
    if contract.status == "signed":
        cert = await get_signature_certificate(db, str(contract.id))
        if cert and isinstance(cert, dict):
            signature_image = cert.get("signature_image")
            signer_designation = cert.get("signer_designation")

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
        signature_image=signature_image,
        signer_designation=signer_designation,
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
