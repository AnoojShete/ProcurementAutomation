from typing import Optional, List, Dict, Any
from datetime import date
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


# --- Documents ---
class UploadDocumentResponse(BaseModel):
    document_id: str
    status: str


class LineItem(BaseModel):
    description: Optional[str] = None
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    line_total: Optional[float] = None


class ExtractedFields(BaseModel):
    line_items: List[Dict[str, Any]] = []
    total: Optional[float] = None
    currency: Optional[str] = None
    document_number: Optional[str] = None
    document_date: Optional[str] = None


class DocumentResponse(BaseModel):
    id: str
    status: str
    document_type: Optional[str] = None
    vendor_id: Optional[str] = None
    vendor_name_raw: Optional[str] = None
    extracted_fields: Dict[str, Any] = {}
    confidence_scores: Dict[str, Any] = {}
    overall_confidence: Optional[float] = None
    needs_review: bool = False
    is_likely_duplicate: bool = False
    duplicate_of_document_id: Optional[str] = None
    file_type: Optional[str] = None
    original_filename: Optional[str] = None
    uploaded_by: Optional[str] = None
    uploaded_at: Optional[str] = None
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None
    error_message: Optional[str] = None


class ReviewCorrectionRequest(BaseModel):
    reviewed_by: str
    document_type: Optional[str] = None
    vendor_name: Optional[str] = None
    extracted_fields: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None


# --- Vendors / payment-detail governance ---
class VerifyPaymentChangeRequest(BaseModel):
    change_request_id: str
    verified_by: str
    channel: str  # e.g. "phone_on_file", "known_contact_email"
    approve: bool = True
    notes: Optional[str] = None


class PaymentChangeRequestResponse(BaseModel):
    id: str
    vendor_id: str
    submitted_by: str
    submitted_at: Optional[str] = None
    source: str
    status: str
    verified_by: Optional[str] = None
    verified_at: Optional[str] = None
    verification_channel: Optional[str] = None
