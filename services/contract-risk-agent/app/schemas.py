from typing import Optional, List, Literal, Dict, Any
from pydantic import BaseModel, ConfigDict


# --- Standard response wrappers ---
class DataResponse(BaseModel):  # {"data": {...}, "meta": {}}
    data: Any
    meta: Optional[Dict[str, Any]] = None


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):  # {"error": ErrorDetail}
    error: ErrorDetail


# --- Contracts ---
class GenerateContractRequest(BaseModel):
    purchase_request_id: str
    template_name: Literal["hardware_purchase", "saas_subscription", "professional_services"]


class SendForSignatureRequest(BaseModel):
    signer_email: Optional[str] = None


class ContractResponse(BaseModel):
    id: str
    purchase_request_id: Optional[str]
    vendor_id: Optional[str]
    template_used: Optional[str]
    version: int
    status: str
    renewal_type: Optional[str]
    notice_period_days: Optional[int]
    contract_end_date: Optional[str]
    generated_at: Optional[str]
    signed_at: Optional[str]
    signed_by: Optional[str]
    esign_provider_ref: Optional[str]
    reconciliation_status: Optional[str]


# --- Risk ---
class RiskFactor(BaseModel):
    feature: str
    contribution: float


class RiskResponse(BaseModel):
    vendor_id: str
    risk_band: Optional[str]
    risk_score: Optional[float]
    top_factors: List[RiskFactor] = []
    model_version: Optional[str]
    scored_at: Optional[str]


class LogOutcomeRequest(BaseModel):
    actual_incident_occurred: bool
    notes: Optional[str] = None
    logged_by: str


class OffboardVendorRequest(BaseModel):
    offboarded_by: str
    reason: Optional[str] = None


# --- E-sign webhook (Prompt 5 scope, added when this service is wired into
# the platform-wide auth/webhook pass) ---
class EsignWebhookPayload(BaseModel):
    provider_event_id: str
    contract_id: str
    signed_by: str
    signed_at: str
    signature: str
