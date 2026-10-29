"""Temporal workflow for daily breach catalogue refresh (Prompt 11 Section 1.1)."""
from datetime import timedelta
from temporalio import activity, workflow

with workflow.unsafe.imports_passed_through():
    from app.database import async_session_factory
    from app.services.breach_catalogue import download_and_store_catalogue


@activity.defn
async def refresh_breach_catalogue_activity() -> dict:
    """Activity that downloads the latest breach catalogue and stores it locally."""
    async with async_session_factory() as session:
        ok, msg, count = await download_and_store_catalogue(session, source="download")
        return {"success": ok, "message": msg, "record_count": count}


@workflow.defn
class BreachCatalogueRefreshWorkflow:
    """Recurring or one-off workflow to refresh the HIBP breach catalogue."""

    @workflow.run
    async def run(self) -> dict:
        return await workflow.execute_activity(
            refresh_breach_catalogue_activity,
            start_to_close_timeout=timedelta(minutes=5),
        )
