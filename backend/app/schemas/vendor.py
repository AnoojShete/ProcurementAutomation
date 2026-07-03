"""Vendor schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator


class VendorBase(BaseModel):
    company_name: Annotated[str, Field(min_length=1, max_length=255)]
    contact_person: Annotated[str, Field(min_length=1, max_length=255)]
    email: Annotated[str, Field(min_length=5, max_length=255)]
    phone: Annotated[str | None, Field(default=None, max_length=32)] = None
    gst_number: Annotated[str, Field(min_length=1, max_length=32)]
    address: Annotated[str, Field(min_length=1, max_length=1000)]
    status: Annotated[str, Field(default="active", max_length=32)] = "active"

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        if "@" not in value or value.startswith("@") or value.endswith("@"):
            raise ValueError("email must be a valid email address")
        return value.lower().strip()


class VendorCreate(VendorBase):
    pass


class VendorUpdate(BaseModel):
    company_name: Annotated[str | None, Field(default=None, max_length=255)] = None
    contact_person: Annotated[str | None, Field(default=None, max_length=255)] = None
    email: Annotated[str | None, Field(default=None, max_length=255)] = None
    phone: Annotated[str | None, Field(default=None, max_length=32)] = None
    gst_number: Annotated[str | None, Field(default=None, max_length=32)] = None
    address: Annotated[str | None, Field(default=None, max_length=1000)] = None
    status: Annotated[str | None, Field(default=None, max_length=32)] = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if "@" not in value or value.startswith("@") or value.endswith("@"):
            raise ValueError("email must be a valid email address")
        return value.lower().strip()


class VendorResponse(VendorBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
