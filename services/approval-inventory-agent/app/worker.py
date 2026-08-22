import asyncio
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
