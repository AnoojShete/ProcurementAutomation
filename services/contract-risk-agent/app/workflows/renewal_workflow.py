from datetime import datetime, timedelta, timezone

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from app.workflows.activities import fetch_contract_renewal_info, publish_renewal_due_event

ALERT_LEVELS = [60, 30, 15]  # days-before-notice-deadline milestones


@workflow.defn
class ContractRenewalWorkflow:
    """Durable timer per contract: fires contract.renewal.due at 60/30/15
    days before the contract's notice deadline. Started once, right after
    a contract is generated with a known contract_end_date."""

    @workflow.run
    async def run(self, contract_id: str) -> dict:
        info = await workflow.execute_activity(
            fetch_contract_renewal_info, contract_id, start_to_close_timeout=timedelta(seconds=30)
        )
        if not info or not info.get("contract_end_date"):
            return {"contract_id": contract_id, "status": "skipped_no_end_date"}

        end_date = datetime.fromisoformat(info["contract_end_date"]).replace(tzinfo=timezone.utc)

        for alert_level in sorted(ALERT_LEVELS, reverse=True):
            fire_at = end_date - timedelta(days=alert_level)
            now = workflow.now()
            if fire_at > now:
                await workflow.sleep(fire_at - now)

            days_remaining = (end_date - workflow.now()).days
            await workflow.execute_activity(
                publish_renewal_due_event,
                args=[
                    contract_id, info.get("vendor_id"), info.get("renewal_type"),
                    info.get("notice_period_days"), info["contract_end_date"], days_remaining, alert_level,
                ],
                start_to_close_timeout=timedelta(seconds=30),
            )

        return {"contract_id": contract_id, "status": "reminders_sent"}
