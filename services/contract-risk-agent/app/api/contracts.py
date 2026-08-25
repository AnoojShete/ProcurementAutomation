from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.config import load_renewal_config
from app.schemas import (
    GenerateContractRequest, SendForSignatureRequest, ContractResponse, DataResponse,
)
from app.services import contract_service

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


@router.post("/generate", response_model=DataResponse)
async def generate_contract(data: GenerateContractRequest, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        contract = await contract_service.generate_contract_for_request(
            db, request.app.state.kafka_producer, data.purchase_request_id, data.template_name
        )
    except contract_service.ContractGenerationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return DataResponse(data=_serialize(contract))


@router.post("/{contract_id}/send-for-signature", response_model=DataResponse)
async def send_for_signature(contract_id: str, data: SendForSignatureRequest, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        contract = await contract_service.send_for_signature(
            db, request.app.state.kafka_producer, contract_id, data.signer_email
        )
    except contract_service.ContractGenerationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return DataResponse(data=_serialize(contract))


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
    return DataResponse(data=_serialize(contract))
