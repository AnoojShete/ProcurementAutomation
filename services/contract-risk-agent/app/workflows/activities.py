"""Temporal activities for the renewal-reminder and drift-monitoring
workflows. Each activity opens its own DB session / Kafka producer since
activities run in the worker process, not the FastAPI request context."""
import logging
from datetime import datetime, timezone

from temporalio import activity

from app.config import settings
from app.database import async_session_factory
from app.models import Contract
from app.kafka.producer import KafkaEventProducer
from app.services.drift_service import check_drift

logger = logging.getLogger(__name__)


@activity.defn
async def fetch_contract_renewal_info(contract_id: str) -> dict | None:
    async with async_session_factory() as session:
        contract = await session.get(Contract, contract_id)
        if contract is None or contract.contract_end_date is None:
            return None
        return {
            "contract_id": contract.id,
            "vendor_id": contract.vendor_id,
            "renewal_type": contract.renewal_type,
            "notice_period_days": contract.notice_period_days,
            "contract_end_date": contract.contract_end_date.isoformat(),
            "status": contract.status,
        }


@activity.defn
async def publish_renewal_due_event(
    contract_id: str, vendor_id: str | None, renewal_type: str | None,
    notice_period_days: int | None, contract_end_date: str, days_remaining: int, alert_level: int
) -> None:
    producer = KafkaEventProducer(settings.kafka_bootstrap_servers)
    await producer.start()
    try:
        await producer.publish_contract_renewal_due(
            contract_id=contract_id,
            vendor_id=vendor_id,
            renewal_type=renewal_type,
            notice_period_days=notice_period_days,
            contract_end_date=contract_end_date,
            days_remaining=days_remaining,
            alert_level=alert_level,
        )
    finally:
        await producer.stop()
    logger.info(f"Published contract.renewal.due for {contract_id} at alert_level={alert_level}")


@activity.defn
async def run_drift_check_activity() -> dict:
    async with async_session_factory() as session:
        return await check_drift(session)
