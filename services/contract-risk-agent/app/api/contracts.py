from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.config import load_renewal_config, settings
from app.schemas import (
    GenerateContractRequest, SendForSignatureRequest, SignContractRequest, ContractResponse, DataResponse,
)
from app.services import contract_service
from app.services import docusign_client
from app.services.esign_client import EsignProviderError, documenso_enabled
from shared.auth import CurrentUser, get_current_user, require_role
from shared.idempotency import get_cached_response, store_response

router = APIRouter()


def _serialize(contract) -> dict:
    return {
        "id": contract.id,
        "purchase_request_id": contract.purchase_request_id,
        "vendor_id": contract.vendor_id,
        "template_used": contract.template,
        "version": contract.version,
        "status": contract.status,
        "renewal_type": contract.renewal_type,
        "notice_period_days": contract.notice_period_days,
        "contract_end_date": contract.contract_end_date.isoformat() if contract.contract_end_date else None,
        "generated_at": contract.generated_at.isoformat() if contract.generated_at else None,
        "signed_at": contract.signed_at.isoformat() if contract.signed_at else None,
        "signed_by": contract.signed_by,
        "esign_provider_ref": contract.esign_provider_ref,
        "reconciliation_status": contract.reconciliation_status,
        "contract_text": contract.contract_text,
    }


@router.get("/esign/status", response_model=DataResponse, dependencies=[Depends(require_role("admin"))])
async def esign_status(db: AsyncSession = Depends(get_db)):
    """E-signature connections and recent DocuSign envelopes, for the
    admin control panel."""
    from sqlalchemy import text
    rows = (await db.execute(text("""
        SELECT c.id::text AS contract_id, c.status, c.esign_provider_ref, c.signed_at, c.signed_by,
               a.payload->>'signer_email' AS signer_email, a.created_at AS sent_at,
               (a.payload->>'automatic')::boolean AS automatic
        FROM contracts c
        JOIN LATERAL (
            SELECT payload, created_at FROM audit_log
            WHERE entity_id = c.id AND action = 'sent_for_signature'
            ORDER BY created_at DESC LIMIT 1
        ) a ON true
        WHERE c.esign_provider_ref LIKE 'docusign-%'
        ORDER BY a.created_at DESC
        LIMIT 10
    """))).mappings().all()
    envelopes = [
        {**dict(r), "live": bool(docusign_client.envelope_id(r["esign_provider_ref"]))} for r in rows
    ]
    return DataResponse(data={
        "docusign": await docusign_client.connection_status(),
        "documenso": {"configured": documenso_enabled()},
        "auto_send": {
            "enabled": settings.esign_auto_send,
            "provider": settings.esign_auto_provider,
            "signer_email": settings.esign_auto_signer_email,
        },
        "envelopes": envelopes,
    })


@router.post(
    "/generate", response_model=DataResponse, dependencies=[Depends(require_role("approver", "finance", "admin"))]
)
async def generate_contract(
    data: GenerateContractRequest,
    request: Request,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    if idempotency_key:
        cached = await get_cached_response(request.app.state.redis, settings.service_name, idempotency_key, scope=user.id)
        if cached is not None:
            return cached

    try:
        contract = await contract_service.generate_contract_for_request(
            db, request.app.state.kafka_producer, data.purchase_request_id, data.template_name
        )
    except contract_service.ContractGenerationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    result = DataResponse(data=_serialize(contract))
    if idempotency_key:
        await store_response(request.app.state.redis, settings.service_name, idempotency_key, result.model_dump(mode="json"), scope=user.id)
    return result


@router.post(
    "/{contract_id}/send-for-signature", response_model=DataResponse,
    dependencies=[Depends(require_role("approver", "finance", "admin"))],
)
async def send_for_signature(contract_id: str, data: SendForSignatureRequest, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        contract = await contract_service.send_for_signature(
            db, request.app.state.kafka_producer, contract_id, data.signer_email, provider=data.provider or "builtin"
        )
    except contract_service.ContractGenerationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return DataResponse(data=_serialize(contract))


@router.post(
    "/{contract_id}/sign",
    response_model=DataResponse,
    dependencies=[Depends(require_role("approver", "finance", "admin"))],
)
async def sign_contract(
    contract_id: str,
    data: SignContractRequest,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Built-in e-sign: the signed-in user signs the contract in the platform.
    The signer's email is the caller's (JWT), never taken from the body."""
    ip_addr = request.headers.get("x-real-ip") or (request.client.host if request.client else None)
    try:
        contract, certificate = await contract_service.sign_contract_digitally(
            db,
            request.app.state.kafka_producer,
            contract_id=contract_id,
            signer_name=data.signer_name.strip(),
            signer_email=user.email,
            signer_designation=data.signer_designation.strip() if data.signer_designation else None,
            signature_data=data.signature_data,
            legal_consent=data.legal_consent,
            ip_address=ip_addr,
            user_agent=request.headers.get("user-agent"),
        )
    except contract_service.ContractGenerationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    serialized = _serialize(contract)
    serialized["signature_certificate"] = certificate
    return DataResponse(data=serialized)


@router.get("/{contract_id}/signature-certificate", response_model=DataResponse)
async def get_signature_certificate(contract_id: str, db: AsyncSession = Depends(get_db)):
    """The built-in e-sign certificate (404 for contracts signed another way)."""
    cert = await contract_service.get_signature_certificate(db, contract_id)
    if cert is None:
        raise HTTPException(status_code=404, detail="Signature certificate not found")
    return DataResponse(data=cert)


@router.post(
    "/{contract_id}/sign-simulated", response_model=DataResponse,
    dependencies=[Depends(require_role("approver", "finance", "admin"))],
)
async def sign_contract_simulated(contract_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Demo only — simulates a provider webhook without real signature verification.
    Disabled when a real e-signature provider is configured.
    """
    import os
    from shared.runtime_env import is_production
    if is_production():
        raise HTTPException(
            status_code=403,
            detail="Simulated signatures are disabled in production. Simulated signing is disabled.",
        )

    enabled = os.environ.get("ENABLE_SIGN_SIMULATED", os.environ.get("APP_ENABLE_SIGN_SIMULATED", "false")).lower() in ("true", "1", "yes")
    if not settings.allow_simulated_signatures or not enabled:
        raise HTTPException(
            status_code=403,
            detail="Simulated signatures are disabled. Simulated signing is disabled. Set ENABLE_SIGN_SIMULATED=true for demo/testing only.",
        )
    if (settings.documenso_api_url or settings.opensign_api_url or docusign_client.docusign_enabled()):
        raise HTTPException(
            status_code=403,
            detail="Simulated signatures are disabled when a real e-signature provider is configured",
        )

    try:
        contract = await contract_service.sign_contract_simulated(
            db, request.app.state.kafka_producer, contract_id
        )
    except contract_service.ContractGenerationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return DataResponse(data=_serialize(contract))


@router.get("/", response_model=DataResponse)
async def list_contracts(limit: int = 100, db: AsyncSession = Depends(get_db)):
    """All contracts, most recent first — backs the tracking dashboard."""
    contracts = await contract_service.list_contracts(db, limit=limit)
    return DataResponse(data=[_serialize(c) for c in contracts], meta={"count": len(contracts)})


@router.get("/renewals-due", response_model=DataResponse)
async def renewals_due(within_days: int | None = None, db: AsyncSession = Depends(get_db)):
    if within_days is None:
        within_days = max(load_renewal_config().get("alert_levels", [60]))
    contracts = await contract_service.get_renewals_due(db, within_days)
    return DataResponse(data=[_serialize(c) for c in contracts], meta={"within_days": within_days})


def _pdf_response(pdf: bytes, filename: str) -> Response:
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
    )


@router.get("/{contract_id}/document")
async def download_contract_document(contract_id: str, db: AsyncSession = Depends(get_db)):
    """The generated contract as a PDF (unsigned working copy)."""
    contract = await contract_service.get_contract(db, contract_id)
    if contract is None:
        raise HTTPException(status_code=404, detail="contract not found")
    pdf = await contract_service.render_document(db, contract)
    return _pdf_response(pdf, contract_service.document_filename(contract, signed=False))


@router.get("/{contract_id}/signed-document")
async def download_signed_contract(contract_id: str, db: AsyncSession = Depends(get_db)):
    """The executed contract, available once signing has completed."""
    contract = await contract_service.get_contract(db, contract_id)
    if contract is None:
        raise HTTPException(status_code=404, detail="contract not found")
    try:
        pdf = await contract_service.render_signed_document(db, contract)
    except contract_service.ContractNotSignedError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except EsignProviderError as e:
        raise HTTPException(status_code=502, detail=f"could not fetch the signed copy from the provider: {e}")
    return _pdf_response(pdf, contract_service.document_filename(contract, signed=True))


@router.get("/{contract_id}", response_model=DataResponse)
async def get_contract(contract_id: str, db: AsyncSession = Depends(get_db)):
    contract = await contract_service.get_contract(db, contract_id)
    if contract is None:
        raise HTTPException(status_code=404, detail="contract not found")
    serialized = _serialize(contract)
    if contract.status == "signed":
        cert = await contract_service.get_signature_certificate(db, contract_id)
        if cert:
            serialized["signature_certificate"] = cert
    return DataResponse(data=serialized)
