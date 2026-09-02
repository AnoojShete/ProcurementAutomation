"""
Periodic usage scanner for the Approval & Inventory Intelligence Agent.

This module runs as a background asyncio task. It reads raw SSO login
events from the synthetic log file (produced by scripts/generate_sso_logs.py),
aggregates them into per-license utilisation counters, writes those counts
to the license_usage table, and then publishes license.usage.updated events
to Kafka.

Data flow (Bug 1 fix explanation):
  RAW SSO LOGS → [this scanner] → license_usage table
                               → license.usage.updated (Kafka, published)
  
  The service PUBLISHES license.usage.updated.
  The service does NOT consume license.usage.updated.
  Consuming your own output would create an infinite loop and is
  architecturally wrong — the raw SSO logs are the input, not the event.
"""
import json
import os
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import async_session_factory
from app.models import License, LicenseUsage
from app.kafka.producer import KafkaEventProducer
from app.services.usage_service import UsageService
from app.config import settings, load_config

logger = logging.getLogger(__name__)

# Path to the synthetic SSO log file produced by scripts/generate_sso_logs.py.
# usage_scanner.py lives at:  services/approval-inventory-agent/app/usage_scanner.py
# Repo root is 3 levels up:   ../../.. from app/
SSO_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "data",
    "synthetic-sso-logs", "sso_login_events.json"
)

# How often (in seconds) to re-scan SSO logs and recompute utilisation
# Configurable via APP_USAGE_SCAN_INTERVAL_SECONDS env var; defaults to 1 hour
SCAN_INTERVAL_SECONDS = int(os.getenv("APP_USAGE_SCAN_INTERVAL_SECONDS", "3600"))


async def run_usage_scanner(kafka_producer: KafkaEventProducer):
    """Background task: periodically ingest SSO logs and publish utilisation events.
    
    Runs forever until CancelledError, sleeping SCAN_INTERVAL_SECONDS between runs.
    On each run:
      1. Load the SSO log JSON produced by scripts/generate_sso_logs.py.
      2. For each (app_name, user_email) pair, count logins in 30/60/90 day windows.
      3. Upsert those counts into the license_usage table.
      4. Call UsageService.check_and_trigger_reclaims() which:
           - Reads from license_usage table
           - Publishes license.usage.updated for each license
           - Creates automatic reclaim requests for underused licenses
    """
    logger.info(
        f"Usage scanner started — will scan every {SCAN_INTERVAL_SECONDS}s "
        f"reading from {SSO_LOG_PATH}"
    )

    while True:
        try:
            await _ingest_sso_logs_and_publish(kafka_producer)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Usage scanner error (will retry next cycle): {e}", exc_info=True)

        try:
            await asyncio.sleep(SCAN_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            logger.info("Usage scanner cancelled during sleep")
            return


async def _ingest_sso_logs_and_publish(producer: KafkaEventProducer):
    """Single scan cycle: load SSO logs, update DB, publish events."""
    if not os.path.exists(SSO_LOG_PATH):
        logger.info(
            f"SSO log file not found at {SSO_LOG_PATH}. "
            "Run scripts/generate_sso_logs.py first to produce synthetic data."
        )
        return

    with open(SSO_LOG_PATH, "r") as f:
        sso_events = json.load(f)

    logger.info(f"Loaded {len(sso_events)} SSO login events from {SSO_LOG_PATH}")

    now = datetime.now(timezone.utc)
    cutoff_30d = now - timedelta(days=30)
    cutoff_60d = now - timedelta(days=60)
    cutoff_90d = now - timedelta(days=90)

    # Aggregate: {(app_name, user_email): {"30d": int, "60d": int, "90d": int, "last": datetime}}
    aggregated: dict[tuple, dict] = {}
    for ev in sso_events:
        app_name = ev.get("app_name")
        user_email = ev.get("user_email")
        ts_raw = ev.get("login_timestamp")
        if not (app_name and user_email and ts_raw):
            continue

        # Parse timestamp — generated with naive isoformat(), make it UTC-aware
        ts = datetime.fromisoformat(ts_raw)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        key = (app_name, user_email)
        if key not in aggregated:
            aggregated[key] = {"30d": 0, "60d": 0, "90d": 0, "last": None}

        if ts >= cutoff_90d:
            aggregated[key]["90d"] += 1
        if ts >= cutoff_60d:
            aggregated[key]["60d"] += 1
        if ts >= cutoff_30d:
            aggregated[key]["30d"] += 1

        if aggregated[key]["last"] is None or ts > aggregated[key]["last"]:
            aggregated[key]["last"] = ts

    async with async_session_factory() as session:
        # Fetch all active licenses so we can map app_name → license_id
        stmt = select(License).where(License.status == "active")
        result = await session.execute(stmt)
        licenses = {lic.app_name: lic for lic in result.scalars().all()}

        for (app_name, user_email), counts in aggregated.items():
            lic = licenses.get(app_name)
            if not lic:
                continue  # No tracked license for this app

            # Upsert into license_usage (insert or update on conflict)
            usage_row = LicenseUsage(
                id=None,  # Will be set via DB default on insert
                license_id=lic.id,
                user_email=user_email,
                last_login_at=counts["last"],
                login_count_30d=counts["30d"],
                login_count_60d=counts["60d"],
                login_count_90d=counts["90d"],
                updated_at=now,
            )

            # Try update first; insert if not exists
            existing_stmt = (
                select(LicenseUsage)
                .where(LicenseUsage.license_id == lic.id)
                .where(LicenseUsage.user_email == user_email)
            )
            existing_result = await session.execute(existing_stmt)
            existing = existing_result.scalar_one_or_none()

            if existing:
                existing.login_count_30d = counts["30d"]
                existing.login_count_60d = counts["60d"]
                existing.login_count_90d = counts["90d"]
                existing.last_login_at = counts["last"]
                existing.updated_at = now
            else:
                import uuid
                new_usage = LicenseUsage(
                    id=str(uuid.uuid4()),
                    license_id=lic.id,
                    user_email=user_email,
                    last_login_at=counts["last"],
                    login_count_30d=counts["30d"],
                    login_count_60d=counts["60d"],
                    login_count_90d=counts["90d"],
                    updated_at=now,
                )
                session.add(new_usage)

        await session.commit()
        logger.info(
            f"Updated license_usage table with {len(aggregated)} user×app entries "
            f"from SSO log"
        )

        # Now compute utilisation and publish license.usage.updated + trigger reclaims
        await UsageService.check_and_trigger_reclaims(session, producer)
