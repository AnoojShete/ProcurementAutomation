from datetime import datetime
from typing import Optional, List, Literal, Dict, Any
from pydantic import BaseModel, ConfigDict

# --- Standard response wrappers ---
class DataResponse(BaseModel): # {"data": {...}, "meta": {}}
    data: Any
    meta: Optional[Dict[str, Any]] = None

class ErrorDetail(BaseModel):  # {"code": str, "message": str}
    code: str
    message: str

class ErrorResponse(BaseModel): # {"error": ErrorDetail}
    error: ErrorDetail

# --- Request schemas ---
class CreatePurchaseRequest(BaseModel):
    request_type: Literal["hardware", "license", "saas", "reclaim"]
    requested_by: str
    department: str
    vendor_id: Optional[str] = None
    amount: float
    currency: str = "INR"
    items: Optional[list[dict]] = None
    comments: Optional[str] = None

class ApprovalAction(BaseModel):
    decided_by: str
    comments: Optional[str] = None

# --- Response schemas ---
class ApprovalHistoryResponse(BaseModel):
    id: str
    decision: str
    decided_by: str
    decision_level: Optional[str]
    escalated: bool
    comments: Optional[str]
    decided_at: Optional[datetime]
    model_config = ConfigDict(from_attributes=True)


class PurchaseRequestResponse(BaseModel):
    id: str
    request_type: str
    requested_by: str
    department: str
    vendor_id: Optional[str]
    amount: float
    currency: str
    spend_tier: Optional[str]
    status: str
    approval_chain: Optional[list[str]]
    current_approver_index: int
    sla_deadline: Optional[datetime]
    items: Optional[list[dict]]
    is_backordered: bool
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    approval_history: Optional[List[ApprovalHistoryResponse]] = None
    model_config = ConfigDict(from_attributes=True)

class InventoryItemResponse(BaseModel):
    id: str
    sku: str
    name: str
    category: Optional[str]
    total_quantity: int
    available_quantity: int
    reserved_quantity: int
    unit_cost: Optional[float]
    currency: Optional[str]
    location: Optional[str]
    model_config = ConfigDict(from_attributes=True)

class InboxItemResponse(BaseModel):
    request_id: str
    request_type: str
    requested_by: str
    department: str
    amount: float
    currency: str
    spend_tier: str
    sla_deadline: Optional[str]
    created_at: Optional[str]

class LicenseResponse(BaseModel):
    id: str
    vendor_id: Optional[str]
    app_name: str
    total_seats: int
    active_seats_30d: Optional[int] = 0
    active_seats_60d: Optional[int] = 0
    active_seats_90d: Optional[int] = 0
    utilisation_score: Optional[float] = 0.0
    cost_per_seat: Optional[float]
    period_end: Optional[str]
    status: str
    model_config = ConfigDict(from_attributes=True)
