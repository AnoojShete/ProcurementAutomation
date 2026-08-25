import logging

from temporalio.client import Client

from app.config import settings

logger = logging.getLogger(__name__)


async def start_renewal_workflow(contract_id: str) -> None:
    """Starts the durable 60/30/15-day renewal reminder timer for a
    contract. Best-effort: a Temporal outage shouldn't block contract
    generation, so failures are logged, not raised."""
    from app.workflows.renewal_workflow import ContractRenewalWorkflow

    try:
        client = await Client.connect(settings.temporal_host, namespace=settings.temporal_namespace)
        await client.start_workflow(
            ContractRenewalWorkflow.run,
            contract_id,
            id=f"contract-renewal-{contract_id}",
            task_queue=settings.temporal_task_queue,
        )
    except Exception as e:
        logger.warning(f"Could not start renewal workflow for contract {contract_id}: {e}")
