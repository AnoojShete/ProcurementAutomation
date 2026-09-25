from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.config import load_renewal_config, settings
from app.schemas import (
    GenerateContractRequest, SendForSignatureRequest, SignContractRequest, ContractResponse, DataResponse,
)
from app.services import contract_service
from shared.auth import require_role
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


@router.post(
    "/generate", response_model=DataResponse, dependencies=[Depends(require_role("approver", "finance", "admin"))]
)
async def generate_contract(
    data: GenerateContractRequest,
    request: Request,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
):
    if idempotency_key:
        cached = await get_cached_response(request.app.state.redis, settings.service_name, idempotency_key)
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
        await store_response(request.app.state.redis, settings.service_name, idempotency_key, result.model_dump(mode="json"))
    return result


@router.post(
    "/{contract_id}/send-for-signature", response_model=DataResponse,
    dependencies=[Depends(require_role("approver", "finance", "admin"))],
)
async def send_for_signature(contract_id: str, data: SendForSignatureRequest, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        contract = await contract_service.send_for_signature(
            db, request.app.state.kafka_producer, contract_id, data.signer_email, provider=data.provider or "documenso"
        )
    except contract_service.ContractGenerationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return DataResponse(data=_serialize(contract))


@router.post(
    "/{contract_id}/sign",
    response_model=DataResponse,
    dependencies=[Depends(require_role("requester", "approver", "finance", "admin"))],
)
async def sign_contract(
    contract_id: str,
    data: SignContractRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Executes a legally binding electronic signature under the ESIGN Act and UETA.
    Generates a cryptographic SHA-256 seal and stores the audit certificate."""
    ip_addr = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    try:
        contract, certificate = await contract_service.sign_contract_digitally(
            db,
            request.app.state.kafka_producer,
            contract_id=contract_id,
            signer_name=data.signer_name,
            signer_email=data.signer_email,
            signature_data=data.signature_data,
            legal_consent=data.legal_consent,
            ip_address=ip_addr,
            user_agent=user_agent,
        )
    except contract_service.ContractGenerationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    serialized = _serialize(contract)
    serialized["signature_certificate"] = certificate
    return DataResponse(data=serialized)


@router.get("/{contract_id}/signature-certificate", response_model=DataResponse)
async def get_signature_certificate(contract_id: str, db: AsyncSession = Depends(get_db)):
    """Retrieves the cryptographic signature certificate and audit record."""
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
    if not settings.allow_simulated_signatures or settings.documenso_api_url or settings.opensign_api_url:
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
