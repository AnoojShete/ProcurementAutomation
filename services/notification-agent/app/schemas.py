from typing import Optional, List, Dict, Any
from datetime import datetime
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


# --- Notification log ---
class NotificationLogEntry(BaseModel):
    id: str
    recipient: str
    channel: str
    event_type: str
    template_name: Optional[str]
    subject: Optional[str]
    priority: Optional[str]
    related_entity_id: Optional[str]
    status: str
    error: Optional[str] = None
    sent_at: Optional[datetime]
    created_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)
