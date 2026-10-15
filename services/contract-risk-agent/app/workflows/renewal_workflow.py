import asyncio
from datetime import date, datetime, timedelta, timezone

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from app.services.renewal_schedule import notice_deadline, reminder_schedule
    from app.workflows.activities import fetch_contract_renewal_info, publish_renewal_due_event

ALERT_LEVELS = [60, 30, 15]  # days-before-notice-deadline milestones
# Workflows started before Oct 16 counted from the end date and replay
# that way; new ones take the patched branch (Temporal versioning).
NOTICE_DEADLINE_PATCH = "renewal-from-notice-deadline"


@workflow.defn
class ContractRenewalWorkflow:
    """Durable timer per contract: fires contract.renewal.due at 60/30/15
    days before the contract's notice deadline (end date − notice period).
    Started once, right after a contract is generated with a known
    contract_end_date."""

    @workflow.run
    async def run(self, contract_id: str) -> dict:
        info = await workflow.execute_activity(
            fetch_contract_renewal_info, contract_id, start_to_close_timeout=timedelta(seconds=30)
        )
        if not info or not info.get("contract_end_date"):
            return {"contract_id": contract_id, "status": "skipped_no_end_date"}

        end_date = datetime.fromisoformat(info["contract_end_date"]).replace(tzinfo=timezone.utc)
        alert_levels = info.get("milestone_days") or ALERT_LEVELS

        if workflow.patched(NOTICE_DEADLINE_PATCH):
            end_day = date.fromisoformat(info["contract_end_date"][:10])
            deadline = notice_deadline(end_day, info.get("notice_period_days"))
            for reminder in reminder_schedule(end_day, info.get("notice_period_days"), alert_levels, workflow.now()):
                now = workflow.now()
                if reminder.fire_at > now:
                    # asyncio.sleep inside a workflow is Temporal's durable timer.
                    await asyncio.sleep((reminder.fire_at - now).total_seconds())
                await workflow.execute_activity(
                    publish_renewal_due_event,
                    args=[
                        contract_id, info.get("vendor_id"), info.get("renewal_type"),
                        info.get("notice_period_days"), info["contract_end_date"],
                        (end_date - workflow.now()).days, reminder.alert_level, deadline.isoformat(),
                    ],
                    start_to_close_timeout=timedelta(seconds=30),
                )
            return {"contract_id": contract_id, "status": "reminders_sent"}

        # Pre-Oct 16 behaviour, kept only so running workflows replay.
        for alert_level in sorted(alert_levels, reverse=True):
            fire_at = end_date - timedelta(days=alert_level)
            now = workflow.now()
            if fire_at > now:
                # asyncio.sleep inside a workflow is Temporal's durable timer
                # (temporalio 1.6 has no workflow.sleep — calling it crashed
                # every renewal workflow, so no reminder was ever sent).
                await asyncio.sleep((fire_at - now).total_seconds())

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
