"""BEC-fraud control: bank/payment-detail re-verification.

ANY change to bank account number, routing/IFSC code, or payment
beneficiary name on an EXISTING vendor goes into a pending, dual-control
state — never a direct update to the live field, no matter how the change
arrived (portal, email-derived document, API). OLD payment details stay
active for any pending/future payment until a *different* user than the
submitter verifies the change through a channel already on file.
"""
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, List

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Vendor, VendorPaymentChangeRequest
from app.services.audit import write_audit_log

PAYMENT_FIELDS = ("bank_account_number", "routing_code", "payment_beneficiary_name")


class SameSubmitterError(Exception):
    """The user verifying a payment-detail change must be different from
    whoever submitted it (dual control) — this is raised when they match."""


class ChangeRequestNotFoundError(Exception):
    pass


@dataclass
class PaymentChangeDetection:
    changed_fields: List[str]


def _detect_changes(vendor: Vendor, new_bank_account: Optional[str], new_routing: Optional[str], new_beneficiary: Optional[str]) -> List[str]:
    changed = []
    if new_bank_account and new_bank_account != vendor.bank_account_number:
        changed.append("bank_account_number")
    if new_routing and new_routing != vendor.routing_code:
        changed.append("routing_code")
    if new_beneficiary and new_beneficiary != vendor.payment_beneficiary_name:
        changed.append("payment_beneficiary_name")
    return changed


async def submit_payment_change(
    db: AsyncSession, kafka_producer, vendor: Vendor, *,
    new_bank_account: Optional[str], new_routing: Optional[str], new_beneficiary: Optional[str],
    submitted_by: str, source: str, document_id: Optional[str] = None,
) -> Optional[VendorPaymentChangeRequest]:
    """Called whenever a new/changed payment detail is observed for a
    vendor that already exists. Vendors created for the first time (no
    prior live value to protect) get their initial payment details set
    directly by the caller instead — this function is only for changes to
    an EXISTING vendor's live fields."""
    changed_fields = _detect_changes(vendor, new_bank_account, new_routing, new_beneficiary)
    if not changed_fields:
        return None

    change = VendorPaymentChangeRequest(
        id=str(uuid.uuid4()),
        vendor_id=vendor.id,
        submitted_by=submitted_by,
        submitted_at=datetime.now(timezone.utc),
        source=source,
        document_id=document_id,
        previous_bank_account_number=vendor.bank_account_number,
        previous_routing_code=vendor.routing_code,
        previous_beneficiary_name=vendor.payment_beneficiary_name,
        new_bank_account_number=new_bank_account or vendor.bank_account_number,
        new_routing_code=new_routing or vendor.routing_code,
        new_beneficiary_name=new_beneficiary or vendor.payment_beneficiary_name,
        status="pending",
        created_at=datetime.now(timezone.utc),
    )
    db.add(change)

    # Flip the flag but leave the live bank_account_number/routing_code/
    # payment_beneficiary_name fields untouched — they remain authoritative
    # for any pending/future payment until verified.
    vendor.payment_details_pending_verification = True
    vendor.updated_at = datetime.now(timezone.utc)

    await db.flush()

    await write_audit_log(
        db, entity_type="vendor", entity_id=vendor.id, action="payment_details_change_flagged",
        payload={
            "change_request_id": change.id,
            "submitted_by": submitted_by,
            "source": source,
            "fields_changed": changed_fields,
            "document_id": document_id,
        },
    )

    if kafka_producer is not None:
        await kafka_producer.publish_vendor_payment_details_flagged(
            vendor_id=vendor.id,
            change_request_id=change.id,
            submitted_by=submitted_by,
            source=source,
            fields_changed=changed_fields,
            flagged_at=change.submitted_at,
        )

    return change


async def verify_payment_change(
    db: AsyncSession, change: VendorPaymentChangeRequest, vendor: Vendor, *,
    verified_by: str, channel: str, approve: bool, notes: Optional[str] = None,
) -> VendorPaymentChangeRequest:
    """Dual control: verified_by must differ from change.submitted_by.
    `channel` must describe a channel already on file (e.g. a phone number
    from the vendor's known contact record) — this service trusts the
    caller's attestation of that (the human process is: call the number
    already on file, not one from the change request itself) and logs it
    verbatim into audit_log.payload for the record."""
    if verified_by == change.submitted_by:
        raise SameSubmitterError(
            f"verifier '{verified_by}' cannot be the same user who submitted this change"
        )

    now = datetime.now(timezone.utc)
    change.verified_by = verified_by
    change.verified_at = now
    change.verification_channel = channel
    change.verification_notes = notes

    if approve:
        change.status = "verified"
        vendor.bank_account_number = change.new_bank_account_number
        vendor.routing_code = change.new_routing_code
        vendor.payment_beneficiary_name = change.new_beneficiary_name
    else:
        change.status = "rejected"
        # OLD details remain live — nothing to change on the vendor row.

    # Only clear the pending flag if no other change request for this
    # vendor is still open.
    from sqlalchemy import select
    result = await db.execute(
        select(VendorPaymentChangeRequest).where(
            VendorPaymentChangeRequest.vendor_id == vendor.id,
            VendorPaymentChangeRequest.status == "pending",
            VendorPaymentChangeRequest.id != change.id,
        )
    )
    still_pending = result.scalars().first() is not None
    vendor.payment_details_pending_verification = still_pending
    vendor.updated_at = now

    await db.flush()

    await write_audit_log(
        db, entity_type="vendor", entity_id=vendor.id,
        action="payment_details_change_verified" if approve else "payment_details_change_rejected",
        payload={
            "change_request_id": change.id,
            "submitted_by": change.submitted_by,
            "verified_by": verified_by,
            "verification_channel": channel,
            "notes": notes,
            "approved": approve,
        },
    )
    return change
