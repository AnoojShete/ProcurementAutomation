"""Seed sample vendor data."""
from __future__ import annotations

from ..crud.vendor import create_vendor, get_all_vendors
from ..database import Base, SessionLocal, engine
from ..schemas.vendor import VendorCreate
from ..utils.logger import configure_logging

logger = configure_logging()

SAMPLE_VENDORS = [
    VendorCreate(
        company_name="Alpha Procurement Ltd",
        contact_person="Ravi Kumar",
        email="ravi.kumar@alpha.example",
        phone="+91-90000-00001",
        gst_number="GSTALPHA0001",
        address="12 Industrial Park, Pune",
        status="active",
    ),
    VendorCreate(
        company_name="BlueSky Traders",
        contact_person="Neha Singh",
        email="neha.singh@bluesky.example",
        phone="+91-90000-00002",
        gst_number="GSTBLUESKY0002",
        address="44 Supply Road, Mumbai",
        status="active",
    ),
    VendorCreate(
        company_name="Coreline Components",
        contact_person="Arjun Mehta",
        email="arjun.mehta@coreline.example",
        phone="+91-90000-00003",
        gst_number="GSTCORELINE0003",
        address="88 Vendor Street, Bengaluru",
        status="active",
    ),
    VendorCreate(
        company_name="Delta Industrial Services",
        contact_person="Priya Nair",
        email="priya.nair@delta.example",
        phone="+91-90000-00004",
        gst_number="GSTDELTA0004",
        address="5 Logistics Avenue, Chennai",
        status="active",
    ),
    VendorCreate(
        company_name="Evergreen Logistics",
        contact_person="Mohit Verma",
        email="mohit.verma@evergreen.example",
        phone="+91-90000-00005",
        gst_number="GSTEVERGREEN0005",
        address="27 Freight Lane, Hyderabad",
        status="active",
    ),
]


def seed_vendors() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        existing_vendors = {vendor.email for vendor in get_all_vendors(db)}
        created_count = 0
        for vendor_data in SAMPLE_VENDORS:
            if vendor_data.email in existing_vendors:
                continue
            create_vendor(db, vendor_data)
            created_count += 1
        logger.info("Seeded %s vendors", created_count)
    finally:
        db.close()


if __name__ == "__main__":
    seed_vendors()
