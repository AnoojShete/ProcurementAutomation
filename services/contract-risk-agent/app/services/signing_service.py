"""Two-party contract signing through Documenso, on the platform's own pages.

1. send_two_party: the contract PDF goes to Documenso as one envelope with
   two signers in order — the company's signatory, then the vendor — and
   one signature field each, over the "For the Company" / "For the Vendor"
   lines of the PDF. Documenso sends no emails.
2. company_session: the company's signatory opens the contract page; the
   platform checks it is them (JWT email) and the vendor's risk (BR-6),
   then hands the browser their Documenso signing token, which opens
   Documenso's signing frame inside the page.
3. Documenso's webhook (handle_documenso_event) reports the signature. The
   vendor is then emailed a link to /sign#token=… on the platform; the
   token is random and only its SHA-256 is stored.
4. vendor_session: the vendor's page exchanges that link for their
   Documenso signing token and signs in the same frame.
5. When both have signed, Documenso seals the PDF with its certificate and
   adds its signing certificate (audit trail); the contract is marked
   signed (webhook_service.mark_contract_signed) and its signed copy is
   Documenso's PDF.

If a signer declines (Documenso then closes the envelope), the contract
goes back to draft so it can be corrected and sent again.
"""
import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Contract, ContractSigner, Vendor
from app.services import esign_client
from app.services.audit import write_audit_log
from app.services.contract_pdf import render_contract_pdf
from app.services.contract_service import (
    ContractGenerationError, RiskAcknowledgementRequired, VendorBlocked,
    _agreement_title, _contract_amount, build_pdf_input, signing_risk,
)
from shared.eventing import staged

logger = logging.getLogger(__name__)

COMPANY, VENDOR = "company", "vendor"
COMPANY_NAME = "IT Procurement Intelligence Platform"
LEGAL_BASIS = (
    "Signed electronically. Under section 10A of the Information Technology Act, 2000, a contract "
    "formed by electronic means is not unenforceable for that reason alone."
)


class NotTheSigner(Exception):
    """The caller isn't the person this contract is waiting on."""


class SigningLinkInvalid(Exception):
    """Unknown, expired or already-used vendor signing link."""


def embed_host() -> str:
    return (settings.documenso_public_url or settings.documenso_api_url or "").rstrip("/")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def signers_of(db: AsyncSession, contract_id: str) -> list[ContractSigner]:
    rows = await db.execute(
        select(ContractSigner).where(ContractSigner.contract_id == contract_id).order_by(ContractSigner.signing_order)
    )
    return list(rows.scalars().all())


def signer_view(s: ContractSigner) -> dict:
    """What the contract page shows about a signer (never the tokens)."""
    return {
        "party": s.party, "name": s.name, "email": s.email, "status": s.status,
        "signed_at": s.signed_at.isoformat() if s.signed_at else None,
        "rejection_reason": s.rejection_reason,
        "link_expires_at": s.link_expires_at.isoformat() if s.link_expires_at else None,
    }


async def _display_name(db: AsyncSession, email: str) -> str:
    try:
        name = (await db.execute(
            text("SELECT display_name FROM auth_users WHERE lower(email) = lower(:e)"), {"e": email}
        )).scalar_one_or_none()
    except Exception:
        name = None
    return name or email.split("@")[0].replace(".", " ").replace("_", " ").title()


async def send_two_party(
    db: AsyncSession, kafka_producer, contract: Contract, company_email: str,
    vendor_email: Optional[str], vendor_name: Optional[str] = None, company_name: Optional[str] = None,
    automatic: bool = False,
) -> Contract:
    """Sends a draft contract to Documenso for the company, then the vendor,
    to sign. The vendor's risk is checked now as well as at signing, so a
    blocked vendor's contract never goes out."""
    vendor = await db.get(Vendor, contract.vendor_id) if contract.vendor_id else None
    vendor_email = (vendor_email or (vendor.contact_email if vendor else None) or "").strip().lower()
    if not vendor_email or "@" not in vendor_email:
        raise ContractGenerationError(
            "Who signs for the vendor? Enter the vendor signatory's email (the vendor has no contact email on file).")
    if vendor_email == company_email.lower():
        raise ContractGenerationError("The vendor's signatory must be someone other than the company's signatory.")
    risk = await signing_risk(db, contract.vendor_id, spend_amount=await _contract_amount(db, contract))
    if risk.get("signing_blocked"):
        raise VendorBlocked(risk["blocked_reason"])

    company_name = (company_name or "").strip() or await _display_name(db, company_email)
    vendor_name = (vendor_name or "").strip() or (vendor.name if vendor else vendor_email)

    pdf_input = await build_pdf_input(db, contract)
    # The copy that gets signed is the final one: no DRAFT watermark.
    pdf_input.status = "pending_signature"
    slots: dict = {}
    pdf = render_contract_pdf(pdf_input, slots=slots)
    if COMPANY not in slots or VENDOR not in slots:
        raise ContractGenerationError("The contract PDF has no signature lines to sign on.")

    title = f"{_agreement_title(contract)} — {pdf_input.vendor_name}"
    try:
        ref, recipients = await esign_client.documenso_send_envelope(
            str(contract.id), title, pdf,
            [
                esign_client.EnvelopeSigner(COMPANY, company_name, company_email, slots[COMPANY].as_percentages()),
                esign_client.EnvelopeSigner(VENDOR, vendor_name, vendor_email, slots[VENDOR].as_percentages()),
            ],
        )
    except esign_client.EsignProviderError as e:
        raise ContractGenerationError(str(e)) from e

    # A contract sent again after a decline starts with fresh signers.
    await db.execute(delete(ContractSigner).where(ContractSigner.contract_id == contract.id))
    names = {COMPANY: company_name, VENDOR: vendor_name}
    for order, r in enumerate(recipients, start=1):
        db.add(ContractSigner(
            contract_id=contract.id, party=r.party, name=names[r.party], email=r.email, signing_order=order,
            provider_recipient_id=r.recipient_id, provider_token=r.token,
            status="ready" if r.party == COMPANY else "waiting",
        ))
    contract.status = "pending_signature"
    contract.esign_provider_ref = ref
    contract.updated_at = _now()
    await write_audit_log(db, "contract", contract.id, "sent_for_signature", {
        "esign_provider_ref": ref, "provider": "documenso", "signer_email": company_email,
        "vendor_signer_email": vendor_email, "signing_order": [COMPANY, VENDOR], "automatic": automatic,
    })
    outbox = staged(kafka_producer, db)
    if outbox is not None:
        await outbox.publish_notification(
            recipient=company_email, channel="email", template_name="contract_ready_for_signature",
            template_context={"contract_id": str(contract.id), "vendor_name": pdf_input.vendor_name,
                              "provider": "documenso", "provider_ref": ref},
            priority="urgent", related_entity_id=str(contract.id),
        )
    await db.commit()
    await db.refresh(contract)
    return contract


async def _signer(db: AsyncSession, contract_id: str, party: str) -> Optional[ContractSigner]:
    return (await db.execute(
        select(ContractSigner).where(ContractSigner.contract_id == contract_id, ContractSigner.party == party)
    )).scalar_one_or_none()


async def company_session(
    db: AsyncSession, contract_id: str, user_email: str, risk_acknowledged: bool = False,
    ip_address: Optional[str] = None, user_agent: Optional[str] = None,
) -> dict:
    """The company signatory's Documenso token, after checking it is them
    and that the vendor's risk allows signing (acknowledged if needed)."""
    contract = await db.get(Contract, contract_id)
    if contract is None:
        raise ContractGenerationError(f"contract {contract_id} not found")
    signer = await _signer(db, contract_id, COMPANY)
    if contract.status != "pending_signature" or signer is None or not esign_client.documenso_envelope_id(contract.esign_provider_ref):
        raise ContractGenerationError("This contract isn't out for signature in Documenso.")
    if signer.email.lower() != (user_email or "").lower():
        raise NotTheSigner(f"This contract is waiting for {signer.email} to sign for the company.")
    if signer.status == "signed":
        raise ContractGenerationError("You have already signed this contract; it is now with the vendor.")
    risk = await signing_risk(db, contract.vendor_id, spend_amount=await _contract_amount(db, contract))
    if risk.get("signing_blocked"):
        raise VendorBlocked(risk["blocked_reason"])
    if risk["acknowledgement_required"] and not risk_acknowledged:
        raise RiskAcknowledgementRequired(
            f"{risk['acknowledgement_reason']} Acknowledge the vendor's risk before signing.")
    await write_audit_log(db, "contract", contract_id, "signing_opened", {
        "party": COMPANY, "signer_email": signer.email, "ip_address": ip_address, "user_agent": user_agent,
        "vendor_risk_at_signing": {
            "risk_band": risk["risk_band"], "risk_score": risk["risk_score"],
            "acknowledgement_required": risk["acknowledgement_required"],
            "acknowledged": bool(risk_acknowledged and risk["acknowledgement_required"]),
        },
    })
    await db.commit()
    return {"host": embed_host(), "token": signer.provider_token, "name": signer.name, "party": COMPANY,
            "legal_basis": LEGAL_BASIS}


async def _by_link(db: AsyncSession, link_token: str) -> ContractSigner:
    if not link_token or len(link_token) > 200:
        raise SigningLinkInvalid("This signing link isn't valid.")
    signer = (await db.execute(
        select(ContractSigner).where(ContractSigner.link_token_sha256 == _hash(link_token))
    )).scalar_one_or_none()
    if signer is None:
        raise SigningLinkInvalid("This signing link isn't valid. Use the latest email you received.")
    return signer


async def vendor_session(
    db: AsyncSession, link_token: str, ip_address: Optional[str] = None, user_agent: Optional[str] = None,
) -> dict:
    """The vendor's page: what they are signing and, while it is their turn,
    their Documenso token. No account; the emailed link is the credential."""
    signer = await _by_link(db, link_token)
    contract = await db.get(Contract, signer.contract_id)
    vendor = await db.get(Vendor, contract.vendor_id) if contract and contract.vendor_id else None
    company = await _signer(db, signer.contract_id, COMPANY)
    summary = {
        "contract_id": str(signer.contract_id),
        "title": _agreement_title(contract) if contract else "Contract",
        "vendor_name": vendor.name if vendor else signer.name,
        "company_name": COMPANY_NAME,
        "signer_name": signer.name,
        "signer_email": signer.email,
        "company_signer": company.name if company else None,
        "company_signed_at": company.signed_at.isoformat() if company and company.signed_at else None,
        "signed_at": signer.signed_at.isoformat() if signer.signed_at else None,
        "legal_basis": LEGAL_BASIS,
    }
    if signer.status == "signed" or (contract and contract.status == "signed"):
        return {**summary, "state": "signed"}
    if signer.status == "rejected" or contract is None or contract.status != "pending_signature":
        return {**summary, "state": "closed"}
    if signer.link_expires_at and signer.link_expires_at < _now():
        return {**summary, "state": "expired"}
    await write_audit_log(db, "contract", signer.contract_id, "signing_opened", {
        "party": VENDOR, "signer_email": signer.email, "ip_address": ip_address, "user_agent": user_agent,
    })
    await db.commit()
    return {**summary, "state": "ready", "host": embed_host(), "token": signer.provider_token}


async def company_signed_copy(db: AsyncSession, contract: Contract) -> Optional[bytes]:
    """The agreement with the company's signature, while it waits for the
    vendor: our signatory's drawn signature (or their name, when Documenso's
    can't be read), name and time in the company box, and every page marked
    as not yet executed. None unless the company has signed and the vendor
    hasn't; once both have, the sealed copy comes from Documenso."""
    if contract.status != "pending_signature":
        return None
    company = await _signer(db, str(contract.id), COMPANY)
    if company is None or company.status != "signed":
        return None
    pdf_input = await build_pdf_input(db, contract)
    pdf_input.awaiting_vendor = True
    pdf_input.signed_by = f"{company.name} <{company.email}>"
    pdf_input.signed_at = company.signed_at
    pdf_input.signature_image = await esign_client.documenso_signature_image(company.provider_recipient_id)
    return render_contract_pdf(pdf_input)


def _vendor_email(signer: ContractSigner, link: str, vendor_name: str, title: str) -> tuple[str, str]:
    expires = signer.link_expires_at.strftime("%d %b %Y") if signer.link_expires_at else ""
    subject = f"Please sign: {title}"
    body = "\n".join([
        f"Hello {signer.name},",
        "",
        f"{COMPANY_NAME} has signed the agreement below and asks you to sign it for {vendor_name}.",
        "",
        f"  Agreement:  {title}",
        f"  Link valid until: {expires}",
        "",
        "Read and sign it here (no account needed):",
        f"  {link}",
        "",
        "The link is personal to you: please don't forward it. Once you sign, both parties receive the",
        "executed copy, sealed with a digital certificate and a record of who signed and when.",
        "",
        "— IT Procurement",
    ])
    return subject, body


async def issue_vendor_link(db: AsyncSession, contract: Contract, signer: ContractSigner) -> str:
    """A fresh link token for the vendor (any earlier link stops working).
    The token itself is only ever in the email (send_vendor_email, after
    the caller commits)."""
    token = secrets.token_urlsafe(32)
    signer.link_token_sha256 = _hash(token)
    signer.link_expires_at = _now() + timedelta(days=settings.vendor_signing_link_days)
    signer.status = "ready"
    return token


async def send_vendor_email(db: AsyncSession, contract: Contract, signer: ContractSigner, token: str) -> bool:
    """Emails the vendor their signing link. Failures are logged; the
    contract page can send a new link."""
    from shared.mailer import load_settings, send_email
    vendor = await db.get(Vendor, contract.vendor_id) if contract.vendor_id else None
    try:
        link = f"{load_settings().app_base_url}/sign#token={token}"
        subject, body = _vendor_email(signer, link, vendor.name if vendor else signer.name, _agreement_title(contract))
        await send_email(signer.email, subject, body)
        return True
    except Exception as e:
        logger.error(f"Vendor signing email for contract {signer.contract_id} failed: {e}")
        return False


async def resend_vendor_link(db: AsyncSession, contract_id: str) -> ContractSigner:
    contract = await db.get(Contract, contract_id)
    signer = await _signer(db, contract_id, VENDOR)
    company = await _signer(db, contract_id, COMPANY)
    if contract is None or signer is None or contract.status != "pending_signature":
        raise ContractGenerationError("This contract isn't waiting for the vendor's signature.")
    if company is None or company.status != "signed":
        raise ContractGenerationError("The vendor's link is sent once the company has signed.")
    if signer.status == "signed":
        raise ContractGenerationError("The vendor has already signed.")
    token = await issue_vendor_link(db, contract, signer)
    await write_audit_log(db, "contract", contract_id, "vendor_link_sent", {"signer_email": signer.email, "resent": True})
    await db.commit()
    if not await send_vendor_email(db, contract, signer, token):
        raise ContractGenerationError("The new link couldn't be emailed. Check the mail settings and try again.")
    return signer


def _parse_time(value: Optional[str]) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else _now()


async def handle_documenso_event(db: AsyncSession, kafka_producer, body: dict) -> Optional[Contract]:
    """Applies a Documenso webhook to a two-party contract. Safe to replay:
    each signer moves on only once. Returns the contract once both signed."""
    from app.services.webhook_service import WebhookContractNotFoundError, mark_contract_signed

    event = body.get("event")
    doc = body.get("payload") or {}
    contract_id = doc.get("externalId")
    if not contract_id:
        raise WebhookContractNotFoundError("Documenso document has no externalId (not created by this platform)")
    contract = await db.get(Contract, contract_id)
    if contract is None:
        raise WebhookContractNotFoundError(f"contract {contract_id} not found")
    # An event about an earlier envelope (sent before a decline) is ignored.
    if esign_client.documenso_envelope_id(contract.esign_provider_ref) != doc.get("envelopeId"):
        logger.info(f"Documenso {event} for an envelope contract {contract_id} no longer uses; ignored")
        return None

    signers = {s.provider_recipient_id: s for s in await signers_of(db, contract_id)}
    newly_signed, declined = [], None
    for r in doc.get("recipients") or []:
        s = signers.get(str(r.get("id")))
        if s is None:
            continue
        status = r.get("signingStatus")
        if status == "SIGNED" and s.status != "signed":
            s.status, s.signed_at = "signed", _parse_time(r.get("signedAt"))
            newly_signed.append(s)
        elif status == "REJECTED" and s.status != "rejected":
            s.status, s.rejection_reason = "rejected", (r.get("rejectionReason") or "")[:1000]
            declined = s

    vendor = next((s for s in signers.values() if s.party == VENDOR), None)
    company = next((s for s in signers.values() if s.party == COMPANY), None)
    for s in newly_signed:
        await write_audit_log(db, "contract", contract_id, f"{s.party}_signed", {
            "signer_name": s.name, "signer_email": s.email, "signed_at": s.signed_at.isoformat(),
            "provider": "documenso", "esign_provider_ref": contract.esign_provider_ref,
        })
    vendor_token = None
    if company in newly_signed and vendor is not None and vendor.status == "waiting":
        vendor_token = await issue_vendor_link(db, contract, vendor)
        await write_audit_log(db, "contract", contract_id, "vendor_link_sent", {"signer_email": vendor.email})

    if declined is not None:
        await write_audit_log(db, "contract", contract_id, "signature_declined", {
            "party": declined.party, "signer_email": declined.email, "reason": declined.rejection_reason,
        })
        contract.status = "draft"
        contract.esign_provider_ref = None
        contract.updated_at = _now()
        await db.commit()
        return None

    if company and vendor and company.status == vendor.status == "signed":
        signed_by = f"{company.name} <{company.email}>; {vendor.name} <{vendor.email}>"[:255]
        return await mark_contract_signed(
            db, kafka_producer, contract_id=contract_id, signed_by=signed_by,
            signed_at=vendor.signed_at or _parse_time(doc.get("completedAt")),
            provider_event_id=f"documenso-{doc.get('envelopeId')}-completed", source="signed_via_documenso",
        )
    await db.commit()
    if vendor_token:
        await send_vendor_email(db, contract, vendor, vendor_token)
    return None
