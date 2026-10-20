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
