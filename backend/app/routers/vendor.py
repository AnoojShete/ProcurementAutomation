"""Vendor API routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..crud.vendor import create_vendor, delete_vendor, get_all_vendors, get_vendor, update_vendor
from ..database import get_db
from ..schemas.vendor import VendorCreate, VendorResponse, VendorUpdate

router = APIRouter(prefix="/vendors", tags=["vendors"])


@router.post("", response_model=VendorResponse, status_code=status.HTTP_201_CREATED)
def create_vendor_endpoint(payload: VendorCreate, db: Session = Depends(get_db)):
    return create_vendor(db, payload)


@router.get("", response_model=list[VendorResponse])
def list_vendors(db: Session = Depends(get_db)):
    return get_all_vendors(db)


@router.get("/{vendor_id}", response_model=VendorResponse)
def get_vendor_endpoint(vendor_id: int, db: Session = Depends(get_db)):
    vendor = get_vendor(db, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vendor not found")
    return vendor


@router.put("/{vendor_id}", response_model=VendorResponse)
def update_vendor_endpoint(vendor_id: int, payload: VendorUpdate, db: Session = Depends(get_db)):
    vendor = update_vendor(db, vendor_id, payload)
    if vendor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vendor not found")
    return vendor


@router.delete("/{vendor_id}", status_code=status.HTTP_200_OK)
def delete_vendor_endpoint(vendor_id: int, db: Session = Depends(get_db)):
    vendor = delete_vendor(db, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vendor not found")
    return {"message": "Vendor deleted successfully", "vendor_id": vendor_id}
