"""
License usage analytics and reclaim trigger service.

Monitors software license utilisation across the organisation and
automatically creates 'reclaim' purchase requests when usage drops
below configurable thresholds. This helps optimise IT spend by
identifying unused or underused licenses.
"""
import uuid
import logging
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models import License, LicenseUsage, PurchaseRequest
from app.config import load_config
from app.kafka.producer import KafkaEventProducer

logger = logging.getLogger(__name__)


class UsageService:
    """License utilisation analytics with reclaim automation.
    
    Provides both static utility methods (for pure computation/testing)
    and async methods that interact with the database and Kafka.
    """

    @staticmethod
    def compute_utilisation_score(total_seats: int, active_seats_30d: int) -> float:
        """Compute the utilisation score as a ratio of active to total seats.
        
        Args:
            total_seats: Total licensed seats.
            active_seats_30d: Seats with at least one login in the last 30 days.
            
        Returns:
            Float between 0.0 and 1.0 representing utilisation.
            Returns 0.0 if total_seats is 0 (avoids division by zero).
        """
        if total_seats <= 0:
            return 0.0
        return round(active_seats_30d / total_seats, 4)

    @staticmethod
    def should_trigger_reclaim(utilisation_score: float, threshold: float = 0.3) -> bool:
        """Check whether utilisation is low enough to trigger a license reclaim.
        
        A reclaim is triggered when the score is STRICTLY below the threshold.
        At exactly the threshold, no reclaim is triggered.
        
        Args:
            utilisation_score: Current utilisation (0.0 to 1.0).
            threshold: Below this value triggers reclaim (default 0.3 = 30%).
            
        Returns:
            True if a reclaim should be created.
        """
        return utilisation_score < threshold

    @staticmethod
    def should_trigger_warning(utilisation_score: float, threshold: float = 0.5) -> bool:
        """Check whether utilisation is low enough to trigger a warning.
        
        A warning is triggered when the score is STRICTLY below the threshold
        but above the reclaim threshold. This is a softer alert.
        
        Args:
            utilisation_score: Current utilisation (0.0 to 1.0).
            threshold: Below this value triggers a warning (default 0.5 = 50%).
            
        Returns:
            True if a warning should be sent.
        """
        return utilisation_score < threshold

    @staticmethod
    async def compute_utilisation(db: AsyncSession, license_id: str) -> dict:
        """Compute utilisation for a specific license from actual usage data.
        
        Queries the license_usage table to count active users in each
        time window (30/60/90 days) and calculates the utilisation score.
        
        Args:
            db: Async database session.
            license_id: UUID of the license to analyse.
            
        Returns:
            Dict with utilisation metrics, or None if license not found.
        """
        # Fetch the license
        stmt = select(License).where(License.id == license_id)
        result = await db.execute(stmt)
        lic = result.scalar_one_or_none()
        if not lic:
            return None

        # Count active users in each time window
        now = datetime.now(timezone.utc)

        # Users with login_count_30d > 0 are considered active in 30-day window
        active_30d_stmt = (
            select(func.count())
            .select_from(LicenseUsage)
            .where(LicenseUsage.license_id == license_id)
            .where(LicenseUsage.login_count_30d > 0)
        )
        active_60d_stmt = (
            select(func.count())
            .select_from(LicenseUsage)
            .where(LicenseUsage.license_id == license_id)
            .where(LicenseUsage.login_count_60d > 0)
        )
        active_90d_stmt = (
            select(func.count())
            .select_from(LicenseUsage)
            .where(LicenseUsage.license_id == license_id)
            .where(LicenseUsage.login_count_90d > 0)
        )

        active_30d = (await db.execute(active_30d_stmt)).scalar() or 0
        active_60d = (await db.execute(active_60d_stmt)).scalar() or 0
        active_90d = (await db.execute(active_90d_stmt)).scalar() or 0

        # Compute score based on 30-day window (primary metric)
        score = UsageService.compute_utilisation_score(lic.total_seats, active_30d)

        return {
            "license_id": lic.id,
            "vendor_id": lic.vendor_id,
            "app_name": lic.app_name,
            "total_seats": lic.total_seats,
            "active_seats_30d": active_30d,
            "active_seats_60d": active_60d,
            "active_seats_90d": active_90d,
            "utilisation_score": score,
            "period_end": lic.period_end,
        }

    @staticmethod
    async def check_and_trigger_reclaims(db: AsyncSession, producer: KafkaEventProducer):
        """Scan all active licenses and auto-create reclaim requests for underused ones.
        
        For each license below the reclaim threshold:
        1. Compute current utilisation
        2. If below threshold, create a 'reclaim' type purchase request
        3. Publish license.usage.updated event with metrics
        
        This is designed to run periodically (e.g., via a scheduled task).
        """
        config = load_config()
        threshold = config.get("utilisation", {}).get("reclaim_threshold", 0.3)

        # Fetch all active licenses
        stmt = select(License).where(License.status == "active")
        result = await db.execute(stmt)
        licenses = result.scalars().all()

        for lic in licenses:
            usage_data = await UsageService.compute_utilisation(db, lic.id)
            if usage_data is None:
                continue

            score = usage_data["utilisation_score"]

            # Publish utilisation update regardless of threshold
            try:
                await producer.publish_license_usage_updated(usage_data)
            except Exception as e:
                logger.error(f"Failed to publish license usage for {lic.id}: {e}")

            # If below threshold, create reclaim request
            if UsageService.should_trigger_reclaim(score, threshold):
                logger.info(
                    f"License {lic.app_name} ({lic.id}) utilisation {score:.1%} "
                    f"below threshold {threshold:.0%} — creating reclaim request"
                )

                # Check if a pending reclaim already exists for this license
                existing_stmt = (
                    select(PurchaseRequest)
                    .where(PurchaseRequest.request_type == "reclaim")
                    .where(PurchaseRequest.status == "pending_approval")
                    .where(
                        PurchaseRequest.items.contains(
                            [{"license_id": str(lic.id)}]
                        )
                    )
                )
                existing = (await db.execute(existing_stmt)).scalar_one_or_none()
                if existing:
                    logger.info(f"Reclaim request already pending for {lic.id}, skipping")
                    continue

                # Calculate estimated savings
                unused_seats = lic.total_seats - usage_data["active_seats_30d"]
                savings = float(lic.cost_per_seat or 0) * unused_seats

                reclaim_request = PurchaseRequest(
                    id=str(uuid.uuid4()),
                    request_type="reclaim",
                    requested_by="system",
                    department="IT",
                    vendor_id=lic.vendor_id,
                    amount=savings,
                    currency=lic.currency or "INR",
                    spend_tier="auto",
                    approval_chain=[],
                    status="pending_approval",
                    items=[{
                        "license_id": str(lic.id),
                        "app_name": lic.app_name,
                        "unused_seats": unused_seats,
                        "utilisation_score": score,
                    }],
                    comments=(
                        f"Auto-generated: {lic.app_name} utilisation at "
                        f"{score:.1%}, {unused_seats} unused seats"
                    ),
                )
                db.add(reclaim_request)
                await db.commit()

    @staticmethod
    async def get_license_usage_summary(db: AsyncSession, license_id: str) -> dict:
        """Get detailed usage stats for a specific license.
        
        Returns license info plus per-user usage breakdown.
        """
        usage_data = await UsageService.compute_utilisation(db, license_id)
        if not usage_data:
            return None

        # Get per-user breakdown
        stmt = select(LicenseUsage).where(LicenseUsage.license_id == license_id)
        result = await db.execute(stmt)
        users = result.scalars().all()

        usage_data["users"] = [
            {
                "user_email": u.user_email,
                "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
                "login_count_30d": u.login_count_30d,
                "login_count_60d": u.login_count_60d,
                "login_count_90d": u.login_count_90d,
            }
            for u in users
        ]

        return usage_data
