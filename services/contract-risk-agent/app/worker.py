import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from app.config import settings
from app.workflows.renewal_workflow import ContractRenewalWorkflow
from app.workflows.drift_workflow import DriftMonitoringWorkflow
from app.workflows.activities import (
    fetch_contract_renewal_info, publish_renewal_due_event, run_drift_check_activity,
)

logger = logging.getLogger(__name__)


async def _ensure_drift_schedule(client: Client):
    """Idempotently start the weekly drift-check workflow. A fixed
    workflow id + cron_schedule means re-running this on every worker
    boot just no-ops against the already-running schedule."""
    try:
        await client.start_workflow(
            DriftMonitoringWorkflow.run,
            id="vendor-risk-drift-monitor",
            task_queue=settings.temporal_task_queue,
            cron_schedule="0 3 * * 0",  # weekly, Sunday 03:00
        )
    except Exception as e:
        logger.info(f"Drift monitor schedule already running or could not be started: {e}")


async def _connect_with_retry(max_attempts: int = 15, delay_seconds: int = 5) -> Client:
    """Temporal (especially auto-setup, which runs its own schema
    migration on first boot) can take a while to accept connections.
    Retries instead of crashing the worker container on a transient
    startup race."""
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await Client.connect(settings.temporal_host, namespace=settings.temporal_namespace)
        except Exception as e:
            last_error = e
            logger.info(f"Temporal not ready yet (attempt {attempt}/{max_attempts}): {e}")
            await asyncio.sleep(delay_seconds)
    raise RuntimeError(f"Could not connect to Temporal after {max_attempts} attempts: {last_error}")


async def main():
    client = await _connect_with_retry()

    await _ensure_drift_schedule(client)

    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[ContractRenewalWorkflow, DriftMonitoringWorkflow],
        activities=[fetch_contract_renewal_info, publish_renewal_due_event, run_drift_check_activity],
    )
    logger.info(f"Starting contract-risk-agent Temporal worker on task queue {settings.temporal_task_queue}")
    await worker.run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
