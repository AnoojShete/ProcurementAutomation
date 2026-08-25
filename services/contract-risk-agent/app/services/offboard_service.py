from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Vendor, Contract
from app.services.audit import write_audit_log


class VendorNotFoundError(Exception):
    pass


async def offboard_vendor(db: AsyncSession, kafka_producer, vendor_id: str, offboarded_by: str, reason: str | None) -> dict:
    vendor = await db.get(Vendor, vendor_id)
    if vendor is None:
        raise VendorNotFoundError(f"vendor {vendor_id} not found")

    now = datetime.now(timezone.utc)
    vendor.status = "inactive"
    vendor.portal_access_revoked = True
    vendor.data_retention_flag = True
    vendor.offboarded_at = now
    vendor.offboarded_by = offboarded_by

    # Flag active contracts for a human to do final reconciliation — never
    # auto-close, since final invoice/payment status needs confirming first.
    result = await db.execute(
        select(Contract).where(Contract.vendor_id == vendor_id, Contract.status.in_(["draft", "pending_signature", "signed"]))
    )
    contracts = list(result.scalars().all())
    for c in contracts:
        c.reconciliation_status = "pending_review"
        c.updated_at = now

    await write_audit_log(
        db, "vendor", vendor_id, "offboarded",
        {"offboarded_by": offboarded_by, "reason": reason, "contracts_flagged": [c.id for c in contracts]},
    )
    await db.commit()

    if kafka_producer is not None:
        await kafka_producer.publish_vendor_offboarded(
            vendor_id=vendor_id,
            offboarded_by=offboarded_by,
            offboarded_at=now,
            contracts_flagged=[c.id for c in contracts],
            data_retention_flag=True,
        )

    return {
        "vendor_id": vendor_id,
        "status": "inactive",
        "portal_access_revoked": True,
        "contracts_flagged": [c.id for c in contracts],
        "offboarded_at": now.isoformat(),
    }
