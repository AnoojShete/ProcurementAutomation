import asyncio
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
    release_inventory_lock
)
from app.workflows.approval_workflow import ApprovalWorkflow

async def main():
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
            release_inventory_lock
        ],
    )
    
    print(f"Starting Temporal worker on task queue: {settings.temporal_task_queue}")
    await worker.run()

if __name__ == "__main__":
    asyncio.run(main())
