import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from app.config import settings
from app.workflows.renewal_workflow import ContractRenewalWorkflow
from app.workflows.activities import fetch_contract_renewal_info, publish_renewal_due_event

logger = logging.getLogger(__name__)


async def _stop_retired_drift_schedule(client: Client):
    """The weekly PSI drift check belonged to the retired ML risk model
    (ml/archive/). Stacks started before its removal still have its cron
    workflow; end it so it stops failing every week (merge review G4).
    The weekly monitoring report (GET /vendors/risk-monitoring/weekly-report)
    replaces it."""
    try:
        await client.get_workflow_handle("vendor-risk-drift-monitor").terminate(
            reason="PSI drift monitoring retired with the ML risk model")
        logger.info("Stopped the retired vendor-risk-drift-monitor workflow")
    except Exception:
        pass  # never started, or already ended


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

    await _stop_retired_drift_schedule(client)

    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[ContractRenewalWorkflow],
        activities=[fetch_contract_renewal_info, publish_renewal_due_event],
    )
    logger.info(f"Starting contract-risk-agent Temporal worker on task queue {settings.temporal_task_queue}")
    await worker.run()


if __name__ == "__main__":
    # JSON lines with the correlation id, like the API (FR-07: searchable in Loki).
    from shared.logging.configure import configure_logging
    configure_logging(f"{settings.service_name}-worker")
    asyncio.run(main())
