"""Notifications for the feature-expansion events: who gets each one, at
what priority, and that every template renders (budget, obligations,
RFQs, deliveries)."""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.kafka import consumer
from app.services import routing
from app.services.templating import render_template
from tests.test_event_schemas import HANDLER_EXTRAS, SAMPLE_PAYLOADS


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.mark.parametrize("event,payload,expected", [
    ("budget.threshold_crossed", {"status": "over"}, "urgent"),
    ("budget.threshold_crossed", {"status": "warning"}, "digest"),
    ("contract.obligation.due", {"kind": "breach"}, "urgent"),
    ("contract.obligation.due", {"kind": "overdue", "days_left": -3}, "urgent"),
    ("contract.obligation.due", {"kind": "due", "days_left": 7}, "urgent"),
    ("contract.obligation.due", {"kind": "due", "days_left": 30}, "digest"),
    ("rfq.issued", {}, "urgent"),
    ("rfq.awarded", {}, "urgent"),
    ("goods.received", {"complete": True}, "digest"),
])
def test_priority(event, payload, expected):
    assert routing.decide_priority(event, payload) == expected


def _calls(event, payload, **lookups):
    sent = []

    async def notify(db, **kw):
        sent.append(kw)
        return "urgent"
    patches = [patch.object(consumer.dispatcher, "notify", notify)]
    for name, value in lookups.items():
        patches.append(patch.object(consumer.directory, name, AsyncMock(side_effect=value) if callable(value) else AsyncMock(return_value=value)))
    for p in patches:
        p.start()
    try:
        session = AsyncMock()
        session.__aenter__.return_value = session
        with patch.object(consumer, "async_session_factory", return_value=session):
            run(consumer.dispatch(event, {"event_type": event, "payload": payload}))
    finally:
        for p in patches:
            p.stop()
    return sent


def test_budget_goes_to_its_owner_or_finance():
    sent = _calls("budget.threshold_crossed", SAMPLE_PAYLOADS["budget.threshold_crossed"], budget_owner="cfo@acme.test")
    assert sent[0]["recipient"] == "cfo@acme.test" and sent[0]["context"]["portal_url"].endswith("/app/budgets/b-1")
    sent = _calls("budget.threshold_crossed", SAMPLE_PAYLOADS["budget.threshold_crossed"], budget_owner=None)
    assert sent[0]["recipient"] == "finance_head@users.procurement.local"


def test_obligation_goes_to_its_owner_then_the_requester():
    sent = _calls("contract.obligation.due", SAMPLE_PAYLOADS["contract.obligation.due"])
    assert sent[0]["recipient"] == "it-owner@acme.test"
    payload = {**SAMPLE_PAYLOADS["contract.obligation.due"], "owner_email": None}
    sent = _calls("contract.obligation.due", payload, requester_for_contract_id="alice@acme.test")
    assert sent[0]["recipient"] == "alice@acme.test"


def test_rfq_invitation_to_every_invited_vendor():
    contacts = {"v-1": "sales@acme.test", "v-2": "vendor-v-2@vendors.procurement.local"}
    sent = _calls("rfq.issued", SAMPLE_PAYLOADS["rfq.issued"], rfq_items=[{"name": "Laptop", "quantity": 25}],
                  vendor_contact=lambda db, v: contacts[v], vendor_name=lambda db, v: v.upper())
    assert [s["recipient"] for s in sent] == ["sales@acme.test", "vendor-v-2@vendors.procurement.local"]
    assert all(s["template_name"] == "rfq_invitation" and s["context"]["items"] for s in sent)


def test_rfq_award_to_winner_and_thanks_to_the_others():
    sent = _calls("rfq.awarded", SAMPLE_PAYLOADS["rfq.awarded"], vendor_contact=lambda db, v: f"{v}@x.test",
                  vendor_name=lambda db, v: v)
    assert [(s["recipient"], s["template_name"]) for s in sent] == [
        ("v-1@x.test", "rfq_awarded"), ("v-2@x.test", "rfq_not_selected"), ("v-3@x.test", "rfq_not_selected")]


def test_goods_received_goes_to_the_requester():
    sent = _calls("goods.received", SAMPLE_PAYLOADS["goods.received"], requester_for_request_id="alice@acme.test")
    assert sent[0]["recipient"] == "alice@acme.test"


def test_vendor_without_contact_gets_a_placeholder():
    from app.services import directory
    assert directory.vendor_placeholder("12345678-aaaa") == "vendor-12345678@vendors.procurement.local"


@pytest.mark.parametrize("payload,needle", [
    ({"status": "over"}, "over its amount"), ({"status": "warning"}, "past its warning threshold")])
def test_budget_wording(payload, needle):
    _, body = render_template("budget_threshold_crossed",
                              {**SAMPLE_PAYLOADS["budget.threshold_crossed"], **HANDLER_EXTRAS["budget.threshold_crossed"], **payload})
    assert needle in body


def test_obligation_subject_says_breach():
    subject, _ = render_template("contract_obligation_due", {**SAMPLE_PAYLOADS["contract.obligation.due"],
                                                             **HANDLER_EXTRAS["contract.obligation.due"], "kind": "breach"})
    assert subject.startswith("Breach: Warranty duration")


def test_rfq_invitation_quotes_the_reference_and_items():
    subject, body = render_template("rfq_invitation", {**SAMPLE_PAYLOADS["rfq.issued"], **HANDLER_EXTRAS["rfq.issued"]})
    assert "RFQ-3F9A2C" in subject and "Developer laptop × 25\n" in body and "confidential until the deadline" in body
    assert "25 Oct 2026, 17:00 UTC" in body


def test_goods_received_lists_asset_tags():
    _, body = render_template("goods_received", {**SAMPLE_PAYLOADS["goods.received"], **HANDLER_EXTRAS["goods.received"]})
    assert "line 1: 30 received (asset tags: LT-0101, LT-0102)\n" in body and "rest is still to come" in body
    assert "20 Oct 2026, 10:00 UTC" in body


@pytest.mark.parametrize("template", ["rfq_awarded", "rfq_not_selected"])
def test_award_templates_render(template):
    subject, body = render_template(template, {**SAMPLE_PAYLOADS["rfq.awarded"], **HANDLER_EXTRAS["rfq.awarded"]})
    assert "RFQ-3F9A2C" in subject and "Acme IT Supplies Inc" in body
    if template == "rfq_awarded":
        assert "INR 2,287,500" in body


def test_dates_are_written_for_people():
    assert consumer._when("2026-10-25T17:00:00+00:00") == "25 Oct 2026, 17:00 UTC"
    assert consumer._when(None) is None


# ── Approval stages, reminders and the vendor (checklist A2) ────────────────

APPROVAL_REQUESTED = {
    "request_id": "r-1", "request_type": "hardware", "requested_by": "asha@acme.test", "department": "IT",
    "amount": 90000, "currency": "INR", "spend_tier": "manager+finance",
    "approval_chain": ["dept_manager", "finance_head"], "sla_deadline": "2026-10-25T17:00:00Z",
}


def _no_action_link():
    return patch.object(consumer, "_mint_action_url", AsyncMock(return_value=(None, None)))


def test_approval_request_goes_to_the_people_holding_the_level():
    levels = {"dept_manager": ["boss@acme.test", "deputy@acme.test"]}
    with _no_action_link():
        sent = _calls("approval.requested", APPROVAL_REQUESTED, approvers_for_level=lambda db, l, a=None: levels.get(l, []))
    approver_sent = [s for s in sent if s["template_name"] == "approval_requested"]
    assert [s["recipient"] for s in approver_sent] == ["boss@acme.test", "deputy@acme.test"]
    assert approver_sent[0]["context"]["portal_url"].endswith("/app/requests/r-1?step=approval")
    user_sent = [s for s in sent if s["template_name"] == "request_submitted"]
    assert [s["recipient"] for s in user_sent] == ["asha@acme.test"]


def test_approval_request_without_assigned_people_keeps_the_level_mailbox():
    with _no_action_link():
        sent = _calls("approval.requested", APPROVAL_REQUESTED, approvers_for_level=[])
    approver_sent = [s for s in sent if s["template_name"] == "approval_requested"]
    assert [s["recipient"] for s in approver_sent] == ["dept_manager@users.procurement.local"]


def test_approval_at_one_level_asks_the_next_level():
    decided = {"request_id": "r-1", "decision": "approved", "decided_by": "boss@acme.test",
               "decision_level": "level_1_dept_manager", "escalated": False,
               "decided_at": "2026-10-21T10:00:00Z", "comments": None}
    row = type("Row", (), {"requested_by": "asha@acme.test", "department": "IT", "currency": "INR",
                           "request_type": "hardware", "spend_tier": "manager+finance", "sla_deadline": None})()
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.execute.return_value = type("R", (), {"first": lambda self: row})()
    sent = []

    async def notify(db, **kw):
        sent.append(kw)
    with patch.object(consumer.dispatcher, "notify", notify), _no_action_link(), \
         patch.object(consumer.directory, "requester_for_request_id", AsyncMock(return_value="asha@acme.test")), \
         patch.object(consumer.directory, "approval_chain", AsyncMock(return_value=(["dept_manager", "finance_head"], 90000.0))), \
         patch.object(consumer.directory, "approvers_for_level", AsyncMock(return_value=["cfo@acme.test"])), \
         patch.object(consumer.directory, "vendor_for_request", AsyncMock(return_value=None)), \
         patch.object(consumer, "async_session_factory", return_value=session):
        run(consumer.dispatch("approval.decided", {"event_type": "approval.decided", "payload": decided}))
    assert [(s["template_name"], s["recipient"]) for s in sent] == [
        ("approval_decided", "asha@acme.test"), ("approval_requested", "cfo@acme.test")]
    assert sent[1]["context"]["step_index"] == 1


@pytest.mark.parametrize("decision,level", [("approved", "level_2_finance_head"), ("rejected", "level_1_dept_manager")])
def test_last_approval_or_a_rejection_asks_nobody_else(decision, level):
    decided = {"request_id": "r-1", "decision": decision, "decided_by": "x@acme.test", "decision_level": level,
               "escalated": False, "decided_at": "2026-10-21T10:00:00Z", "comments": None}
    sent = _calls("approval.decided", decided, requester_for_request_id="asha@acme.test",
                  approval_chain=(["dept_manager", "finance_head"], 90000.0),
                  vendor_for_request=None)
    assert [s["template_name"] for s in sent] == ["approval_decided"]


def test_vendor_is_told_when_approval_is_decided_final_or_rejected():
    decided = {"request_id": "r-1", "decision": "rejected", "decided_by": "boss@acme.test",
               "decision_level": "level_1_dept_manager", "escalated": False,
               "decided_at": "2026-10-21T10:00:00Z", "comments": "Budget limits exceeded"}
    sent = _calls("approval.decided", decided, requester_for_request_id="asha@acme.test",
                  approval_chain=(["dept_manager"], 90000.0),
                  vendor_for_request="v-1", vendor_name="Acme Ltd", vendor_contact="sales@acme-ltd.test")
    assert [(s["template_name"], s["recipient"]) for s in sent] == [
        ("approval_decided", "asha@acme.test"), ("approval_decided_vendor", "sales@acme-ltd.test")]
    subject, body = render_template("approval_decided_vendor", sent[1]["context"])
    assert "r-1: rejected" in subject and "Acme Ltd" in body and "Budget limits exceeded" in body


def test_sla_reminder_goes_to_the_approvers_with_a_link():
    payload = {"kind": "approval_sla", "entity_type": "purchase_request", "entity_id": "r-1",
               "waiting_since": "2026-10-20T10:00:00Z", "waiting_hours": 36.04, "threshold": "75%",
               "recipient_role": "dept_manager", "link": "/app/requests/r-1?step=approval",
               "detail": "75% of the 48h approval SLA has passed"}
    sent = _calls("reminder.due", payload, approvers_for_level=["boss@acme.test"])
    assert [s["recipient"] for s in sent] == ["boss@acme.test"]
    assert sent[0]["priority_override"] == "urgent"
    subject, body = render_template("reminder_due", sent[0]["context"])
    assert subject == "Reminder: a purchase request is waiting for your approval"
    assert "36.0 hours" in body and "http://localhost:8080/app/requests/r-1?step=approval" in body


def test_signature_reminder_goes_to_the_signer():
    payload = {"kind": "signature_waiting", "entity_type": "contract", "entity_id": "c-1",
               "waiting_since": "2026-10-18T10:00:00Z", "waiting_hours": 72, "threshold": "3d",
               "recipient_role": "signer", "link": "/app/contracts/c-1?action=sign", "detail": None}
    sent = _calls("reminder.due", payload, signer_for_contract="signer@acme.test")
    assert [s["recipient"] for s in sent] == ["signer@acme.test"]


def test_vendor_is_told_when_the_contract_is_signed():
    sent = _calls("contract.signed", SAMPLE_PAYLOADS["contract.signed"], requester_for_contract_id="asha@acme.test",
                  vendor_for_contract="v-1", vendor_name="Acme Ltd", vendor_contact="sales@acme-ltd.test")
    assert [(s["template_name"], s["recipient"]) for s in sent] == [
        ("contract_signed", "asha@acme.test"), ("contract_signed_vendor", "sales@acme-ltd.test")]
    subject, body = render_template("contract_signed_vendor", sent[1]["context"])
    assert subject == "Contract signed: Acme Ltd" and "c-1" in body


def test_sla_escalation_asks_the_next_level_not_the_missed_one():
    """The workflow's escalation notice names the level that missed its SLA
    (template sla_breach_escalation, no built-in): the next level's people
    get an approval request saying it was escalated."""
    row = type("Row", (), {"requested_by": "asha@acme.test", "department": "IT", "currency": "INR",
                           "request_type": "hardware", "spend_tier": "manager+finance", "sla_deadline": None})()
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.execute.return_value = type("R", (), {"first": lambda self: row})()
    sent = []

    async def notify(db, **kw):
        sent.append(kw)
    payload = {"recipient": "dept_manager", "channel": "email", "template_name": "sla_breach_escalation",
               "template_context": {"request_id": "r-1", "decision_level": "level_1_dept_manager"},
               "priority": "urgent", "related_entity_id": "r-1"}
    with patch.object(consumer.dispatcher, "notify", notify), _no_action_link(), \
         patch.object(consumer.directory, "approval_chain", AsyncMock(return_value=(["dept_manager", "finance_head"], 90000.0))), \
         patch.object(consumer.directory, "approvers_for_level", AsyncMock(return_value=["cfo@acme.test"])), \
         patch.object(consumer, "async_session_factory", return_value=session):
        run(consumer.dispatch("notification.send", {"event_type": "notification.send", "payload": payload}))
    assert [(s["template_name"], s["recipient"]) for s in sent] == [("approval_requested", "cfo@acme.test")]
    _, body = render_template("approval_requested", {**APPROVAL_REQUESTED, **sent[0]["context"], "action_url": None,
                                                      "portal_url": "http://x/app/requests/r-1"})
    assert "escalated to you: the dept_manager approval" in body
