"""Client for the e-signature provider.

Documenso (self-hosted in the compose stack, Envelope API
https://docs.documenso.com/developers/public-api) is used for real when
APP_DOCUMENSO_API_URL and APP_DOCUMENSO_API_TOKEN are set. A contract goes
out as one envelope with two signers in order: the company's signatory,
then the vendor. Nothing is emailed by Documenso (distributionMethod NONE):
each signer signs in Documenso's embedded signing frame on the platform's
own pages, opened with their recipient token (signing_service.py). Its
webhooks (POST /webhooks/documenso) record each signature, and the sealed
PDF is fetched back from Documenso for download.

With no provider configured (the default dev/demo stack) request_signature
returns a deterministic simulated reference instead, and signing is
completed by the built-in e-sign, POST /webhooks/esign or the demo-only
sign-simulated route.

DocuSign (app/services/docusign_client.py) is used the same way when its
JWT-grant settings are set and the provider is "docusign".

Provider references:
  documenso-env-<id>    a real Documenso envelope
  docusign-env-<id>     a real DocuSign envelope
  <provider>-ref-<hash> simulated, nothing was sent anywhere
"""
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from typing import Optional

import httpx

from app.config import settings
from app.services import docusign_client

logger = logging.getLogger(__name__)

DOCUMENSO_REF_PREFIX = "documenso-env-"
_TIMEOUT = httpx.Timeout(30.0)


class EsignProviderError(Exception):
    pass


def documenso_enabled() -> bool:
    return bool(settings.documenso_api_url and settings.documenso_api_token)


def documenso_envelope_id(provider_ref: Optional[str]) -> Optional[str]:
    if provider_ref and provider_ref.startswith(DOCUMENSO_REF_PREFIX):
        return provider_ref[len(DOCUMENSO_REF_PREFIX):]
    return None


def live_provider_ref(provider_ref: Optional[str]) -> Optional[str]:
    """The provider name when the contract is out with a real provider
    (it completes there, not in this platform), else None."""
    if documenso_envelope_id(provider_ref):
        return "Documenso"
    if docusign_client.envelope_id(provider_ref):
        return "DocuSign"
    return None


def _simulated_ref(contract_id: str, signer_email: Optional[str], provider: str) -> str:
    digest = hashlib.sha256(f"esign:{provider}:{contract_id}:{signer_email or ''}".encode()).hexdigest()[:16]
    return f"{provider}-ref-{digest}"


def _pdf_page_count(pdf: bytes) -> int:
    return max(1, len(re.findall(rb"/Type\s*/Page(?![s\w])", pdf)))


@dataclass
class EnvelopeSigner:
    """One signer of a Documenso envelope, in signing order. `field` is the
    signature box as page percentages (contract_pdf.SignatureSlot)."""
    party: str
    name: str
    email: str
    field: dict


@dataclass
class EnvelopeRecipient:
    party: str
    email: str
    recipient_id: str
    token: str


def _documenso_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=settings.documenso_api_url.rstrip("/") + "/api/v2",
        headers={"Authorization": settings.documenso_api_token},
        timeout=_TIMEOUT,
    )


def _raise_for(res: httpx.Response, what: str) -> None:
    if res.status_code >= 400:
        raise EsignProviderError(f"Documenso {what} failed ({res.status_code}): {res.text[:300]}")


async def documenso_send_envelope(
    contract_id: str, title: str, pdf: bytes, signers: list[EnvelopeSigner],
) -> tuple[str, list[EnvelopeRecipient]]:
    """Creates the envelope (PDF, signers in order, one signature field
    each), distributes it without emails and returns its provider reference
    and each signer's recipient token."""
    payload = {
        "title": title,
        "type": "DOCUMENT",
        "externalId": contract_id,
        "meta": {
            "signingOrder": "SEQUENTIAL",
            "distributionMethod": "NONE",
            "timezone": "Asia/Kolkata",
            "dateFormat": "dd/MM/yyyy HH:mm",
            "language": "en",
        },
        "recipients": [
            {
                "email": s.email, "name": s.name, "role": "SIGNER", "signingOrder": i + 1,
                "fields": [{"type": "SIGNATURE", "identifier": 0, **s.field}],
            }
            for i, s in enumerate(signers)
        ],
    }
    async with _documenso_client() as client:
        created = await client.post(
            "/envelope/create",
            files={"payload": (None, json.dumps(payload)), "files": ("contract.pdf", pdf, "application/pdf")},
        )
        _raise_for(created, "create envelope")
        envelope_id = created.json()["id"]
        sent = await client.post("/envelope/distribute", json={
            "envelopeId": envelope_id, "meta": {"distributionMethod": "NONE"},
        })
        _raise_for(sent, "distribute envelope")
    by_email = {r["email"].lower(): r for r in sent.json().get("recipients") or []}
    recipients = []
    for s in signers:
        r = by_email.get(s.email.lower())
        if r is None:
            raise EsignProviderError(f"Documenso did not return a recipient for {s.email}")
        recipients.append(EnvelopeRecipient(s.party, s.email, str(r["id"]), r["token"]))
    logger.info(f"Contract {contract_id} sent to Documenso as envelope {envelope_id}")
    return f"{DOCUMENSO_REF_PREFIX}{envelope_id}", recipients


async def request_signature(
    contract_id: str,
    signer_email: Optional[str],
    provider: str = "documenso",
    pdf: Optional[bytes] = None,
    title: str = "Contract",
    signer_name: Optional[str] = None,
) -> str:
    """Routes the contract for signature and returns the provider reference."""
    p_name = (provider or "documenso").strip().lower()
    if p_name == "docusign" and docusign_client.docusign_enabled():
        if not signer_email:
            raise EsignProviderError("a signer email is required to send through DocuSign")
        if not pdf:
            raise EsignProviderError("no contract PDF to send")
        try:
            return await docusign_client.send_envelope(contract_id, signer_email, signer_name or signer_email, pdf, title)
        except docusign_client.DocuSignError as e:
            raise EsignProviderError(str(e)) from e
    if p_name == "documenso" and documenso_enabled():
        # Two signers and their tokens: contract_service sends through
        # documenso_send_envelope instead.
        raise EsignProviderError("Documenso contracts are sent with documenso_send_envelope")
    return _simulated_ref(contract_id, signer_email, p_name)


def _documenso_dsn() -> str:
    if settings.documenso_database_url:
        return settings.documenso_database_url
    base, _, _ = settings.database_url.replace("+asyncpg", "").rpartition("/")
    return f"{base}/documenso"


async def documenso_signature_image(recipient_id: Optional[str]) -> Optional[str]:
    """A signer's drawn signature (PNG data URL) from Documenso's database.
    Documenso only stamps signatures into the PDF once every party has
    signed, and its API doesn't return them, so this reads its "Signature"
    table directly. None when there is none (typed signature, no
    Documenso, or its tables changed in an upgrade); callers fall back to
    the signer's name."""
    if not recipient_id or not documenso_enabled():
        return None
    import asyncpg
    try:
        conn = await asyncpg.connect(_documenso_dsn(), timeout=5)
        try:
            image = await conn.fetchval(
                'SELECT "signatureImageAsBase64" FROM "Signature" WHERE "recipientId" = $1 ORDER BY id DESC LIMIT 1',
                int(recipient_id),
            )
        finally:
            await conn.close()
    except Exception as e:
        logger.warning(f"Could not read the drawn signature of Documenso recipient {recipient_id}: {e}")
        return None
    return image if isinstance(image, str) and image.startswith("data:image/") else None


async def download_signed_pdf(provider_ref: Optional[str]) -> Optional[bytes]:
    """The provider's sealed PDF for a completed Documenso envelope or
    DocuSign envelope, or None when the contract wasn't signed through a
    live provider."""
    env_id = docusign_client.envelope_id(provider_ref)
    if env_id is not None and docusign_client.docusign_enabled():
        try:
            return await docusign_client.download_combined(env_id)
        except docusign_client.DocuSignError as e:
            raise EsignProviderError(str(e)) from e
    envelope_id = documenso_envelope_id(provider_ref)
    if envelope_id is None or not documenso_enabled():
        return None
    async with _documenso_client() as client:
        res = await client.get(f"/envelope/{envelope_id}")
        _raise_for(res, "get envelope")
        items = res.json().get("envelopeItems") or []
        if not items:
            raise EsignProviderError(f"Documenso envelope {envelope_id} has no document")
        pdf = await client.get(f"/envelope/item/{items[0]['id']}/download", params={"version": "signed"})
        _raise_for(pdf, "signed PDF download")
    return pdf.content
