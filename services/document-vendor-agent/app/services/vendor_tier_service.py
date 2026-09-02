"""Tiered vendor vetting — proportional due-diligence based on transaction value.

Running every check (GSTIN live API, OpenCorporates, sanctions screening) on
a ₹500 local-shop purchase is both impractical and unfair to small vendors
who are legally exempt from GST registration below the threshold. This
module classifies each vendor interaction into one of three tiers and
enforces the appropriate vetting level:

  petty    (<₹5,000)   name + phone + address + receipt only.
                        No GSTIN/OpenCorporates/sanctions screening required.

  standard (₹5k–₹50k)  GSTIN structural + live check, IFSC on payment details.
                        No OpenCorporates/SSL Labs/SEC EDGAR.

  strategic (>₹50k)    Full suite including everything Anjali's risk model covers.

Structuring/purchase-splitting detection: cumulative spend per vendor over
a rolling 90-day window is tracked. If cumulative spend crosses a tier
threshold, the next tier's vetting is retroactively required before any
further purchase is approved. This prevents splitting large orders into
small sub-threshold pieces to avoid scrutiny.

No-GSTIN attestation: when a vendor has no GSTIN, the person onboarding
them must explicitly confirm "this vendor is below the GST registration
threshold" — logged with who confirmed it — rather than the system
silently treating a missing GSTIN as acceptable.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, Vendor
from app.services.audit import write_audit_log

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tier thresholds (INR)
# ---------------------------------------------------------------------------
PETTY_THRESHOLD = 5_000.0      # < this → petty
STANDARD_THRESHOLD = 50_000.0  # < this → standard, >= this → strategic

SPEND_WINDOW_DAYS = 90


class VendorTier(str, Enum):
    PETTY = "petty"
    STANDARD = "standard"
    STRATEGIC = "strategic"


@dataclass
class TierResult:
    tier: VendorTier
    cumulative_spend_90d: float
    required_checks: list[str]


@dataclass
class TierUpgradeEvent:
    vendor_id: str
    old_tier: VendorTier
    new_tier: VendorTier
    cumulative_spend: float
    triggered_at: datetime


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify_tier(amount: float) -> VendorTier:
    """Determine the vetting tier for a single transaction amount."""
    if amount < PETTY_THRESHOLD:
        return VendorTier.PETTY
    if amount < STANDARD_THRESHOLD:
        return VendorTier.STANDARD
    return VendorTier.STRATEGIC


def required_checks_for_tier(tier: VendorTier) -> list[str]:
    """Return the list of vetting checks required for the given tier."""
    if tier == VendorTier.PETTY:
        return ["name", "phone", "address", "receipt"]
    if tier == VendorTier.STANDARD:
        return ["name", "phone", "address", "receipt", "gstin_structural", "gstin_live", "ifsc"]
    # strategic
    return [
        "name", "phone", "address", "receipt",
        "gstin_structural", "gstin_live", "ifsc",
        "opencorporates", "sanctions_screening", "risk_model",
    ]


# ---------------------------------------------------------------------------
# Rolling 90-day spend tracking
# ---------------------------------------------------------------------------

async def get_vendor_spend_90d(db: AsyncSession, vendor_id: str) -> float:
    """Sum of document totals for this vendor in the last 90 days.
    Only counts documents in status='classified' (fully processed)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=SPEND_WINDOW_DAYS)
    result = await db.execute(
        select(func.coalesce(func.sum(Document.total), 0.0))
        .where(
            Document.vendor_id == vendor_id,
            Document.status == "classified",
            Document.uploaded_at >= cutoff,
        )
    )
    return float(result.scalar() or 0.0)


async def check_and_upgrade_tier(
    db: AsyncSession, vendor: Vendor, new_amount: float
) -> TierResult:
    """Calculate cumulative 90-day spend including the new transaction and
    determine if a tier upgrade is required.

    If cumulative spend crosses a tier threshold, the retroactively upgraded
    tier's checks are required before the purchase is approved — not just
    for future purchases.
    """
    existing_spend = await get_vendor_spend_90d(db, vendor.id)
    cumulative = existing_spend + new_amount

    # Tier based on CUMULATIVE spend (structuring detection), not just this transaction
    if cumulative >= STANDARD_THRESHOLD:
        effective_tier = VendorTier.STRATEGIC
    elif cumulative >= PETTY_THRESHOLD:
        effective_tier = VendorTier.STANDARD
    else:
        effective_tier = VendorTier.PETTY

    old_tier_str = vendor.vendor_tier or VendorTier.STANDARD.value
    try:
        old_tier = VendorTier(old_tier_str)
    except ValueError:
        old_tier = VendorTier.STANDARD

    if effective_tier != old_tier:
        logger.info(
            f"Vendor {vendor.id} tier upgraded {old_tier} → {effective_tier} "
            f"(cumulative 90d spend: {cumulative:.2f} INR)"
        )
        vendor.vendor_tier = effective_tier.value
        vendor.updated_at = datetime.now(timezone.utc)
        await db.flush()
        await write_audit_log(
            db, entity_type="vendor", entity_id=vendor.id,
            action="vendor_tier_upgraded",
            payload={
                "old_tier": old_tier.value,
                "new_tier": effective_tier.value,
                "cumulative_spend_90d": cumulative,
                "new_transaction_amount": new_amount,
            },
        )

    return TierResult(
        tier=effective_tier,
        cumulative_spend_90d=cumulative,
        required_checks=required_checks_for_tier(effective_tier),
    )


# ---------------------------------------------------------------------------
# No-GSTIN attestation
# ---------------------------------------------------------------------------

async def confirm_no_gstin(
    db: AsyncSession, vendor: Vendor, confirmed_by: str,
) -> None:
    """Record an explicit attestation that this vendor is below the GST
    registration threshold. Logged to audit_log and written to the vendor
    row — never silently treat a missing GSTIN as acceptable.
    """
    now = datetime.now(timezone.utc)
    vendor.no_gstin_confirmed_by = confirmed_by
    vendor.no_gstin_confirmed_at = now
    vendor.updated_at = now
    await db.flush()
    await write_audit_log(
        db, entity_type="vendor", entity_id=vendor.id,
        action="no_gstin_threshold_confirmed",
        payload={"confirmed_by": confirmed_by, "confirmed_at": now.isoformat()},
    )
