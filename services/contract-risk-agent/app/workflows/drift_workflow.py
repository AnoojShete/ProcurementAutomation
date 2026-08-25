from datetime import timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from app.workflows.activities import run_drift_check_activity


@workflow.defn
class DriftMonitoringWorkflow:
    """Weekly model-drift check. Started with a cron schedule
    (see worker.py) — each run just executes the PSI check once and logs
    the result to MLflow. This is a monitoring signal only: it never
    retrains the model on its own, it just surfaces drift for a human to
    review."""

    @workflow.run
    async def run(self) -> dict:
        return await workflow.execute_activity(
            run_drift_check_activity, start_to_close_timeout=timedelta(minutes=2)
        )
