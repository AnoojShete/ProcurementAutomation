"""Vendor CRUD operations."""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..models.vendor import Vendor
from ..schemas.vendor import VendorCreate, VendorUpdate
from ..utils.exceptions import DuplicateVendorError
from ..utils.logger import configure_logging

logger = configure_logging()


def get_vendor(db: Session, vendor_id: int) -> Vendor | None:
    return db.query(Vendor).filter(Vendor.id == vendor_id).first()


def get_all_vendors(db: Session) -> list[Vendor]:
    return db.query(Vendor).order_by(Vendor.id.asc()).all()


def get_vendor_by_email(db: Session, email: str, exclude_vendor_id: int | None = None) -> Vendor | None:
    query = db.query(Vendor).filter(Vendor.email == email)
    if exclude_vendor_id is not None:
        query = query.filter(Vendor.id != exclude_vendor_id)
    return query.first()


def get_vendor_by_gst_number(
    db: Session, gst_number: str, exclude_vendor_id: int | None = None
) -> Vendor | None:
    query = db.query(Vendor).filter(Vendor.gst_number == gst_number)
    if exclude_vendor_id is not None:
        query = query.filter(Vendor.id != exclude_vendor_id)
    return query.first()


def create_vendor(db: Session, vendor_in: VendorCreate) -> Vendor:
    if get_vendor_by_email(db, vendor_in.email):
        raise DuplicateVendorError("email", vendor_in.email)
    if get_vendor_by_gst_number(db, vendor_in.gst_number):
        raise DuplicateVendorError("gst_number", vendor_in.gst_number)

    vendor = Vendor(**vendor_in.model_dump())
    db.add(vendor)
    db.commit()
    db.refresh(vendor)
    logger.info("Created vendor id=%s email=%s", vendor.id, vendor.email)
    return vendor


def update_vendor(db: Session, vendor_id: int, vendor_in: VendorUpdate) -> Vendor | None:
    vendor = get_vendor(db, vendor_id)
    if vendor is None:
        return None

    update_data = vendor_in.model_dump(exclude_unset=True)
    if "email" in update_data and get_vendor_by_email(db, update_data["email"], exclude_vendor_id=vendor_id):
        raise DuplicateVendorError("email", update_data["email"])
    if "gst_number" in update_data and get_vendor_by_gst_number(
        db, update_data["gst_number"], exclude_vendor_id=vendor_id
    ):
        raise DuplicateVendorError("gst_number", update_data["gst_number"])

    for field_name, value in update_data.items():
        setattr(vendor, field_name, value)

    db.commit()
    db.refresh(vendor)
    logger.info("Updated vendor id=%s", vendor.id)
    return vendor


def delete_vendor(db: Session, vendor_id: int) -> Vendor | None:
    vendor = get_vendor(db, vendor_id)
    if vendor is None:
        return None

    db.delete(vendor)
    db.commit()
    logger.info("Deleted vendor id=%s", vendor_id)
    return vendor
