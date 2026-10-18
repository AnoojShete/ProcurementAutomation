"""FR-03: an approver is reminded at 50 % and 80 % of the SLA, and a
decision stops the remaining reminders. Runs the real ApprovalWorkflow in
Temporal's time-skipping test server (downloaded on first use; the tests
skip if it can't be fetched) with the activities faked."""
import asyncio
import uuid
from datetime import timedelta

import pytest
from temporalio import activity
from temporalio.client import Client
from temporalio.worker import Worker

from app.workflows.approval_workflow import ApprovalSignal, ApprovalWorkflow

SLA_HOURS = 10
reminders: list = []
decisions: list = []


@activity.defn(name="fetch_request_details")
async def fake_fetch(request_id: str) -> dict:
    return {"id": request_id, "approval_chain": ["dept_manager"], "sla_hours": SLA_HOURS,
            "request_type": "hardware", "items": [], "reminder_percents": [50, 80]}


@activity.defn(name="publish_approval_reminder")
async def fake_reminder(request_id: str, level: str, since: str, percent: int, sla_hours: int) -> None:
    reminders.append(percent)


@activity.defn(name="record_approval_decision")
async def fake_record(*args) -> None:
    decisions.append(args[1])


def _noop(name):
    @activity.defn(name=name)
    async def noop(*args) -> None:
        return None
    return noop


ACTIVITIES = [fake_fetch, fake_reminder, fake_record] + [_noop(n) for n in (
    "update_request_status", "publish_approval_decided_event", "publish_notification_event",
    "release_inventory_lock", "release_hardware_reservations", "set_reclaim_cooldown", "revoke_email_tokens_activity",
)]


@pytest.fixture(scope="module")
def env():
    from temporalio.testing import WorkflowEnvironment
    loop = asyncio.new_event_loop()
    try:
        e = loop.run_until_complete(asyncio.wait_for(WorkflowEnvironment.start_time_skipping(), 120))
    except Exception as exc:  # no network to fetch the test server
        loop.close()
        pytest.skip(f"Temporal time-skipping test server unavailable: {exc}")
    yield loop, e
    loop.run_until_complete(e.shutdown())
    loop.close()


def _run(env, decide_after_hours):
    """Start the workflow, optionally approve after N (skipped) hours, and
    return (reminders sent, decisions recorded, final status)."""
    loop, e = env
    reminders.clear(); decisions.clear()

    async def go():
        client: Client = e.client
        async with Worker(client, task_queue="t", workflows=[ApprovalWorkflow], activities=ACTIVITIES):
            handle = await client.start_workflow(ApprovalWorkflow.run, "r-1", id=f"wf-{uuid.uuid4()}", task_queue="t")
            if decide_after_hours is not None:
                await e.sleep(timedelta(hours=decide_after_hours))
                await handle.signal(ApprovalWorkflow.approval_signal,
                                    ApprovalSignal(decision="approved", decided_by="a@x.test", level_index=0))
            return await handle.result()
    result = loop.run_until_complete(go())
    return list(reminders), list(decisions), result["status"]


def test_no_decision_reminds_at_50_and_80_percent_then_sla(env):
    sent, decided, status = _run(env, None)
    assert sent == [50, 80]
    assert status == "rejected" and decided == ["rejected"]  # last level timed out


def test_decision_after_the_first_reminder_stops_the_second(env):
    sent, decided, status = _run(env, SLA_HOURS * 0.6)
    assert sent == [50]
    assert status == "approved"


def test_decision_before_any_reminder_sends_none(env):
    sent, _, status = _run(env, SLA_HOURS * 0.2)
    assert sent == []
    assert status == "approved"
