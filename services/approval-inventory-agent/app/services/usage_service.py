"""
License usage analytics and reclaim trigger service.

Monitors software license utilisation across the organisation and
automatically creates 'reclaim' purchase requests when an anomaly model
detects unusual decline patterns. The flat utilisation-threshold check has
been replaced by an IsolationForest anomaly score (computed by
app/ml/usage_anomaly.py using SHAP TreeExplainer for attribution).

Trigger logic (replaces the old flat threshold):
  anomaly_score > anomaly_threshold  →  create reclaim request
  (configurable in config.yaml: utilisation.anomaly_threshold, default 0.6)

The raw utilisation_score is still computed and published in
license.usage.updated events alongside the anomaly_score + top_factors.
"""
import json
import os
import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models import License, LicenseUsage, PurchaseRequest, ApprovalHistory, AuditLog
from app.config import load_config, settings
from app.kafka.producer import KafkaEventProducer
from app.ml.usage_anomaly import get_scorer

logger = logging.getLogger(__name__)

# Path to SSO log for feeding the anomaly scorer.
# usage_service.py lives at: services/approval-inventory-agent/app/services/
# Repo root is 4 parent dirs up:  app/services → app → approval-inventory-agent → services → repo-root
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.join(_HERE, "..", "..", "..", "..", "..")
_SSO_LOG_PATH = os.path.join(
    _REPO_ROOT, "data", "synthetic-sso-logs", "sso_login_events.json"
)


def _load_sso_events() -> list[dict]:
    """Load SSO events from the synthetic log; returns [] if file missing."""
    try:
        with open(_SSO_LOG_PATH) as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning(
            f"SSO log not found at {_SSO_LOG_PATH}. "
            "Anomaly scorer will return 0 for all licenses."
        )
        return []
    except Exception as e:
        logger.error(f"Failed to load SSO log: {e}")
        return []


class UsageService:
    """License utilisation analytics with ML anomaly-driven reclaim automation.

    Provides both static utility methods (for pure computation/testing)
    and async methods that interact with the database and Kafka.
    """

    last_scoring_run: Optional[datetime] = datetime.now(timezone.utc)

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
        """Legacy flat-threshold check (kept for backward compatibility in tests).

        Prefer should_trigger_reclaim_ml() for new code.

        Args:
            utilisation_score: Current utilisation (0.0 to 1.0).
            threshold: Below this value triggers reclaim (default 0.3 = 30%).

        Returns:
            True if a reclaim should be created.
        """
        return utilisation_score < threshold

    @staticmethod
    def should_trigger_reclaim_ml(
        anomaly_score: float, threshold: float = 0.6
    ) -> bool:
        """Check whether the ML anomaly score exceeds the reclaim threshold.

        Args:
            anomaly_score: IsolationForest anomaly score (0.0 normal, 1.0 anomalous).
            threshold: Above this value triggers reclaim (default 0.6).

        Returns:
            True if a reclaim should be created.
        """
        return anomaly_score > threshold

    @staticmethod
    def should_trigger_warning(utilisation_score: float, threshold: float = 0.5) -> bool:
        """Check whether utilisation is low enough to trigger a warning.

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
        Also runs the ML anomaly scorer with SHAP attribution.

        Args:
            db: Async database session.
            license_id: UUID of the license to analyse.

        Returns:
            Dict with utilisation metrics + anomaly_score + top_factors,
            or None if license not found.
        """
        stmt = select(License).where(License.id == license_id)
        result = await db.execute(stmt)
        lic = result.scalar_one_or_none()
        if not lic:
            return None

        now = datetime.now(timezone.utc)
        UsageService.last_scoring_run = now

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

        score = UsageService.compute_utilisation_score(lic.total_seats, active_30d)

        # ── ML anomaly scoring ─────────────────────────────────────────────
        sso_events = _load_sso_events()
        # Filter to this license's app_name
        license_events = [
            ev for ev in sso_events
            if ev.get("app_name") == lic.app_name
        ]
        anomaly_result = get_scorer().score(
            license_id=str(lic.id),
            sso_events=license_events,
            total_seats=lic.total_seats,
            now=now,
        )

        anomaly_score = anomaly_result.get("anomaly_score")
        from app.config import get_anomaly_thresholds
        watch_th, anomalous_th = get_anomaly_thresholds()
        if anomaly_score is None:
            anomaly_status = "insufficient_history"
        elif anomaly_score >= anomalous_th:
            anomaly_status = "anomalous"
        elif anomaly_score >= watch_th:
            anomaly_status = "watch"
        else:
            anomaly_status = "normal"

        days_since = anomaly_result.get("days_since_last_login")
        if days_since is None:
            max_last_login_stmt = (
                select(func.max(LicenseUsage.last_login_at))
                .where(LicenseUsage.license_id == license_id)
            )
            max_last = (await db.execute(max_last_login_stmt)).scalar()
            if max_last:
                if max_last.tzinfo is None:
                    max_last = max_last.replace(tzinfo=timezone.utc)
                days_since = int(max(0.0, (now - max_last).total_seconds() / 86400.0))
            else:
                days_since = 90

        from app.models import Vendor
        vendor_name = None
        if lic.vendor_id:
            vend_stmt = select(Vendor).where(Vendor.id == lic.vendor_id)
            vend = (await db.execute(vend_stmt)).scalar_one_or_none()
            if vend:
                vendor_name = vend.name

        return {
            "license_id": lic.id,
            "id": lic.id,
            "vendor_id": lic.vendor_id,
            "vendor_name": vendor_name,
            "app_name": lic.app_name,
            "total_seats": lic.total_seats,
            "assigned_seats": lic.assigned_seats or 0,
            "active_seats_30d": active_30d,
            "active_seats_60d": active_60d,
            "active_seats_90d": active_90d,
            "utilisation_score": score,
            "period_start": lic.period_start.isoformat() if lic.period_start else None,
            "period_end": lic.period_end.isoformat() if lic.period_end else None,
            "reclaim_cooldown_until": lic.reclaim_cooldown_until.isoformat() if lic.reclaim_cooldown_until else None,
            "last_scored_at": now.isoformat(),
            "days_since_last_login": days_since,
            # ── Anomaly detection (ML) ─────────────────────────────────────
            "anomaly_score": anomaly_score,
            "anomaly_status": anomaly_status,
            "top_factors": anomaly_result.get("top_factors", []),
            "model_version": anomaly_result.get("model_version"),
            "cost_per_seat": float(lic.cost_per_seat) if lic.cost_per_seat else None,
            "currency": lic.currency or "INR",
            "status": lic.status,
        }


    @staticmethod
    async def check_and_trigger_reclaims(db: AsyncSession, producer: KafkaEventProducer):
        """Scan all active licenses and auto-create reclaim requests for anomalous ones.

        Replaces the old flat utilisation-threshold check with an ML anomaly score
        from the IsolationForest model. For each license above the anomaly_threshold:
          1. Compute current utilisation + anomaly_score + top_factors
          2. Publish license.usage.updated event (with all fields)
          3. Create a 'reclaim' type purchase request (if none open already)

        This is designed to run periodically (e.g., via a scheduled task).
        """
        config = load_config()
        anomaly_threshold = config.get("utilisation", {}).get("anomaly_threshold", 0.6)

        stmt = select(License).where(License.status == "active")
        result = await db.execute(stmt)
        licenses = result.scalars().all()

        for lic in licenses:
            usage_data = await UsageService.compute_utilisation(db, lic.id)
            if usage_data is None:
                continue

            anomaly_score = usage_data["anomaly_score"]
            utilisation_score = usage_data["utilisation_score"]

            # Publish utilisation + anomaly update regardless of threshold
            try:
                await producer.publish_license_usage_updated(usage_data)
            except Exception as e:
                logger.error(f"Failed to publish license usage for {lic.id}: {e}")

            # ── ML-driven reclaim trigger ──────────────────────────────────
            now = datetime.now(timezone.utc)
            if lic.reclaim_cooldown_until and lic.reclaim_cooldown_until > now:
                continue

            if UsageService.should_trigger_reclaim_ml(anomaly_score, anomaly_threshold):
                logger.info(
                    f"License {lic.app_name} ({lic.id}) anomaly_score={anomaly_score:.3f} "
                    f"exceeds threshold {anomaly_threshold} — creating reclaim request. "
                    f"top_factors={usage_data['top_factors']}"
                )

                open_statuses_to_skip = ("rejected", "fulfilled", "cancelled")
                existing_stmt = (
                    select(PurchaseRequest)
                    .where(PurchaseRequest.request_type == "reclaim")
                    .where(PurchaseRequest.status.in_(["pending_approval", "pending_grace_period"]))
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

                unused_seats = lic.total_seats - lic.assigned_seats
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
                    sla_deadline=now + timedelta(hours=48),
                    status="pending_grace_period",
                    items=[{
                        "license_id": str(lic.id),
                        "app_name": lic.app_name,
                        "unused_seats": unused_seats,
                        "utilisation_score": utilisation_score,
                        "anomaly_score": anomaly_score,
                        "top_factors": usage_data["top_factors"],
                    }],
                    comments=(
                        f"Auto-generated: {lic.app_name} anomaly_score={anomaly_score:.3f}, "
                        f"{unused_seats} unused seats. "
                        f"Top factors: {usage_data['top_factors']}"
                    ),
                )
                db.add(reclaim_request)
                await db.flush()

                try:
                    await producer.publish_notification(
                        recipient="license_owner",
                        channel="email",
                        template_name="license_reclaim_warning",
                        template_context={
                            "grace_period_ends_at": (now + timedelta(days=7)).isoformat()
                        },
                        priority="urgent",
                        related_entity_id=reclaim_request.id,
                    )
                except Exception as e:
                    logger.error(f"Failed to publish notification for reclaim {reclaim_request.id}: {e}")

                try:
                    from temporalio.client import Client
                    temporal_client = await Client.connect(
                        settings.temporal_host, namespace=settings.temporal_namespace
                    )
                    await temporal_client.start_workflow(
                        "ApprovalWorkflow",
                        reclaim_request.id,
                        id=f"approval-{reclaim_request.id}",
                        task_queue=settings.temporal_task_queue,
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to start Temporal workflow (will retry): {e}"
                    )

                await db.commit()

    @staticmethod
    async def get_license_usage_summary(db: AsyncSession, license_id: str) -> dict:
        """Get detailed usage stats for a specific license.

        Returns license info plus per-user usage breakdown and ML anomaly result.
        """
        usage_data = await UsageService.compute_utilisation(db, license_id)
        if not usage_data:
            return None

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

    @staticmethod
    async def get_usage_history(db: AsyncSession, license_id: str, days: int = 90) -> list[dict]:
        """Return daily active user counts for the last 90 days for a specific license."""
        stmt = select(License).where(License.id == license_id)
        result = await db.execute(stmt)
        lic = result.scalar_one_or_none()
        if not lic:
            return None

        now = datetime.now(timezone.utc)
        sso_events = _load_sso_events()
        license_events = [ev for ev in sso_events if ev.get("app_name") == lic.app_name]

        from collections import defaultdict
        daily_users = defaultdict(set)
        for ev in license_events:
            ts_raw = ev.get("login_timestamp") or ev.get("ts")
            if ts_raw:
                try:
                    t = datetime.fromisoformat(ts_raw)
                    d_str = t.strftime("%Y-%m-%d")
                    email = ev.get("user_email")
                    if email:
                        daily_users[d_str].add(email)
                except Exception:
                    pass

        history = []
        for i in range(days - 1, -1, -1):
            day_dt = now - timedelta(days=i)
            day_str = day_dt.strftime("%Y-%m-%d")
            active_count = len(daily_users.get(day_str, set()))
            history.append({"date": day_str, "active_seats": active_count})

        return history

    @staticmethod
    async def get_anomaly_summary(db: AsyncSession) -> dict:
        """Return aggregated anomaly counts, last scoring run, and potential savings."""
        from app.config import get_anomaly_thresholds
        watch_th, anomalous_th = get_anomaly_thresholds()

        stmt = select(License).where(License.status == "active")
        result = await db.execute(stmt)
        licenses = result.scalars().all()

        total = len(licenses)
        anomalous = 0
        watch = 0
        normal = 0
        insufficient = 0
        potential_annual_savings = 0.0

        for lic in licenses:
            usage = await UsageService.compute_utilisation(db, lic.id)
            if not usage or usage.get("anomaly_score") is None:
                insufficient += 1
            else:
                score = usage["anomaly_score"]
                if score >= anomalous_th:
                    anomalous += 1
                    cost = float(lic.cost_per_seat or 0.0)
                    seats = lic.total_seats or 0
                    potential_annual_savings += cost * seats
                elif score >= watch_th:
                    watch += 1
                else:
                    normal += 1

        last_run = UsageService.last_scoring_run
        return {
            "total_licenses": total,
            "anomalous": anomalous,
            "watch": watch,
            "normal": normal,
            "insufficient_history": insufficient,
            "last_scoring_run": last_run.isoformat() if last_run else None,
            "potential_annual_savings": round(potential_annual_savings, 2),
        }

    @staticmethod
    async def get_reclaim_history(db: AsyncSession, license_id: str) -> list[dict]:
        """Return history of reclaim events for a specific license."""
        from app.models import LicenseReclaimHistory
        stmt = (
            select(LicenseReclaimHistory)
            .where(LicenseReclaimHistory.license_id == license_id)
            .order_by(LicenseReclaimHistory.event_at.desc())
        )
        result = await db.execute(stmt)
        rows = result.scalars().all()
        return [
            {
                "id": str(r.id),
                "event_type": r.event_type,
                "event_at": r.event_at.isoformat() if r.event_at else None,
                "by_user": r.by_user,
                "cooldown_set_until": r.cooldown_set_until.isoformat() if r.cooldown_set_until else None,
                "notes": r.notes,
            }
            for r in rows
        ]

    @staticmethod
    async def mark_reviewed(db: AsyncSession, license_id: str, reviewer: str) -> dict:
        """Mark a license as reviewed, logging to reclaim history and setting a 30-day review cooldown."""
        from app.models import License, LicenseReclaimHistory, AuditLog
        stmt = select(License).where(License.id == license_id)
        result = await db.execute(stmt)
        lic = result.scalar_one_or_none()
        if not lic:
            return None

        now = datetime.now(timezone.utc)
        cooldown = now + timedelta(days=30)
        lic.reclaim_cooldown_until = cooldown
        lic.updated_at = now

        entry = LicenseReclaimHistory(
            id=str(uuid.uuid4()),
            license_id=license_id,
            event_type="reviewed",
            event_at=now,
            by_user=reviewer,
            cooldown_set_until=cooldown,
            notes="Marked as reviewed by admin (30-day review cooldown set)",
        )
        db.add(entry)

        audit = AuditLog(
            id=str(uuid.uuid4()),
            entity_type="license",
            entity_id=license_id,
            action="license_marked_reviewed",
            performed_by=reviewer,
            details={"cooldown_set_until": cooldown.isoformat()},
            created_at=now,
        )
        db.add(audit)
        await db.commit()
        await db.refresh(lic)

        return {
            "status": "reviewed",
            "license_id": license_id,
            "reclaim_cooldown_until": cooldown.isoformat(),
        }

