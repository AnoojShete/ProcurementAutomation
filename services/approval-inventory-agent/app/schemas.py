from datetime import datetime
from decimal import Decimal
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
    request_type: Literal["hardware", "license", "saas", "reclaim", "reinstate"]
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
    # Optional rather than required: rows inserted directly via SQL (demo
    # seed scripts, the e2e test's vendor-linking step) bypass
    # create_request's validation and can leave this and other fields
    # unset — the list/tracking endpoints must tolerate that rather than
    # 500ing the whole list over one incomplete row.
    request_type: Optional[str] = None
    requested_by: Optional[str] = None
    department: Optional[str] = None
    vendor_id: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    spend_tier: Optional[str] = None
    status: Optional[str] = None
    approval_chain: Optional[list[str]] = None
    current_approver_index: int = 0
    sla_deadline: Optional[datetime] = None
    items: Optional[list[dict]] = None
    is_backordered: bool = False
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


# --- Anomaly factor schema (matches risk.score.updated top_factors shape) ---
class AnomalyFactor(BaseModel):
    """A single SHAP contribution for one feature.

    Positive contribution → feature pushes toward anomaly (unusual drop/decline).
    Negative contribution → feature pushes toward normal/inlier.
    """
    feature: str
    contribution: float
    direction: Optional[str] = "increasing_risk"


class UsageAnomalyResponse(BaseModel):
    """Response for GET /licenses/{id}/usage-anomaly."""
    license_id: str
    app_name: str
    anomaly_score: float
    top_factors: List[AnomalyFactor]
    model_version: str
    utilisation_score: float
    active_seats_30d: int
    total_seats: int


class LicenseResponse(BaseModel):
    id: str
    vendor_id: Optional[str] = None
    vendor_name: Optional[str] = None
    app_name: str
    total_seats: int
    active_seats_30d: Optional[int] = 0
    active_seats_60d: Optional[int] = 0
    active_seats_90d: Optional[int] = 0
    utilisation_score: Optional[float] = 0.0
    # ── ML anomaly fields ─────────────────────────────────────────────────────
    anomaly_score: Optional[float] = None
    anomaly_status: Optional[str] = "normal"
    top_factors: Optional[List[AnomalyFactor]] = None
    model_version: Optional[str] = None
    last_scored_at: Optional[str] = None
    days_since_last_login: Optional[int] = 0
    # ─────────────────────────────────────────────────────────────────────────
    cost_per_seat: Optional[Decimal] = None
    currency: Optional[str] = "INR"
    assigned_seats: Optional[int] = 0
    reclaim_cooldown_until: Optional[str] = None
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    status: str
    model_config = ConfigDict(from_attributes=True)


class UsageHistoryEntry(BaseModel):
    date: str
    active_seats: int


class LicenseAnomalySummary(BaseModel):
    total_licenses: int
    anomalous: int
    watch: int
    normal: int
    insufficient_history: int
    last_scoring_run: Optional[str] = None
    potential_annual_savings: float


class ReclaimHistoryEntry(BaseModel):
    id: Optional[str] = None
    event_type: str
    event_at: str
    by_user: Optional[str] = None
    cooldown_set_until: Optional[str] = None
    notes: Optional[str] = None

