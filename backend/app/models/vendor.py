"""Vendor ORM model."""
from __future__ import annotations

from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint, func

from ..database import Base


class Vendor(Base):
    __tablename__ = "vendors"
    __table_args__ = (
        UniqueConstraint("email", name="uq_vendors_email"),
        UniqueConstraint("gst_number", name="uq_vendors_gst_number"),
    )

    id = Column(Integer, primary_key=True, index=True)
    company_name = Column(String(255), nullable=False, index=True)
    contact_person = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False, index=True, unique=True)
    phone = Column(String(32), nullable=True)
    gst_number = Column(String(32), nullable=False, index=True, unique=True)
    address = Column(Text, nullable=False)
    status = Column(String(32), nullable=False, default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
