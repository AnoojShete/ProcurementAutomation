import asyncio
import logging
from prometheus_client import start_http_server
from temporalio.client import Client
from temporalio.worker import Worker

from app.config import settings
from app.workflows.activities import (
    fetch_request_details,
    update_request_status,
    record_approval_decision,
    publish_approval_decided_event,
    publish_notification_event,
    release_inventory_lock,
    release_hardware_reservations,
)
from app.workflows.approval_workflow import ApprovalWorkflow

logger = logging.getLogger(__name__)


async def _connect_with_retry(max_attempts: int = 15, delay_seconds: int = 5) -> Client:
    """Retry Temporal connection — the server can take time on first boot."""
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await Client.connect(
                settings.temporal_host, namespace=settings.temporal_namespace
            )
        except Exception as e:
            last_error = e
            logger.info(f"Temporal not ready yet (attempt {attempt}/{max_attempts}): {e}")
            await asyncio.sleep(delay_seconds)
    raise RuntimeError(
        f"Could not connect to Temporal after {max_attempts} attempts: {last_error}"
    )


async def main():
    client = await _connect_with_retry()

    # approval_escalated_total (app/metrics.py) is only ever updated by the
    # record_approval_decision activity below, which runs in THIS process,
    # not the API container — expose it on its own metrics-only server.
    # infra/prometheus/prometheus.yml scrapes it as approval-inventory-agent-worker:9100.
    start_http_server(9100)

    client = await Client.connect(settings.temporal_host, namespace=settings.temporal_namespace)
    
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[ApprovalWorkflow],
        activities=[
            fetch_request_details,
            update_request_status,
            record_approval_decision,
            publish_approval_decided_event,
            publish_notification_event,
            release_inventory_lock,
            release_hardware_reservations,
        ],
    )

    logger.info(f"Starting Temporal worker on task queue: {settings.temporal_task_queue}")
    await worker.run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
