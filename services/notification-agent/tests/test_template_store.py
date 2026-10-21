"""Notification templates edited from the Control Panel
(app/services/template_store.py, app/api/templates.py): overrides win over
the built-in file, a bad override never loses an email, edits are checked
when saved, the sandbox keeps form-entered text away from Python internals,
and only admins reach the API."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import templates as templates_api
from app.database import get_db
from app.services import dispatcher, template_store
from app.services.template_store import TemplateValidationError
from shared.auth import get_current_user
from shared.auth.middleware import CurrentUser

APPROVAL = {
    "request_id": "PR-1", "requested_by": "asha@acme.test", "department": "IT", "amount": "1200",
    "currency": "INR", "request_type": "software", "spend_tier": "manager", "sla_deadline": "Friday",
}


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _row(**kw):
    base = dict(name="approval_requested", description="", subject="S", body="B", extra_recipients="",
                enabled=True, is_custom=False, updated_by="admin@acme.test", updated_at=None)
    return SimpleNamespace(**(base | kw))


def _db(row=None):
    """A session whose template lookup returns `row` (None = no override)."""
    db = MagicMock()
    db.execute = AsyncMock(return_value=SimpleNamespace(first=lambda: row))
    return db


class TestBuiltins:
    def test_every_builtin_splits_into_subject_and_body(self):
        names = template_store.builtin_names()
        assert "approval_requested" in names and "contract_signed" in names
        for name in names:
            subject, body = template_store.builtin_source(name)
            assert subject and body and not subject.lower().startswith("subject:")

    def test_placeholders_come_from_the_builtin(self):
        allowed = template_store.allowed_placeholders("approval_requested")
        assert {"request_id", "amount", "department", "portal_url"} <= set(allowed)

    def test_every_builtin_has_its_event_and_audience_described(self):
        assert set(template_store.builtin_names()) <= set(template_store.TEMPLATE_INFO)


class TestValidate:
    def test_unknown_placeholder_in_a_builtin_override_is_refused(self):
        with pytest.raises(TemplateValidationError, match="invoice_total"):
            template_store.validate("approval_requested", "Approve {{ invoice_total }}", "x", [])

    def test_syntax_error_says_where(self):
        with pytest.raises(TemplateValidationError, match="body: line 2"):
            template_store.validate("approval_requested", "S", "ok\n{% if %}", [])

    def test_bad_recipient_is_refused(self):
        with pytest.raises(TemplateValidationError, match="not-an-email"):
            template_store.validate("approval_requested", "S", "B", ["not-an-email"])

    def test_new_template_cannot_take_a_builtin_name(self):
        with pytest.raises(TemplateValidationError, match="built-in"):
            template_store.validate("contract_signed", "S", "B", [], creating=True)

    def test_custom_template_may_use_any_placeholder(self):
        template_store.validate("quarterly_review", "Review for {{ vendor_name }}", "{{ anything }}", [],
                                creating=True)

    def test_multi_line_subject_is_refused(self):
        with pytest.raises(TemplateValidationError, match="one line"):
            template_store.validate("approval_requested", "a\nb", "B", [])


class TestRender:
    def test_no_override_uses_the_builtin_file(self):
        email = run(template_store.render(_db(None), "approval_requested", APPROVAL))
        assert "approve 1200 INR software" in email.subject and email.enabled

    def test_override_wins(self):
        row = _row(subject="Please approve {{ request_id }}", body="Amount {{ amount }} {{ currency }}",
                   extra_recipients="audit@acme.test, cfo@acme.test")
        email = run(template_store.render(_db(row), "approval_requested", APPROVAL))
        assert email.subject == "Please approve PR-1"
        assert email.body == "Amount 1200 INR"
        assert email.extra_recipients == ["audit@acme.test", "cfo@acme.test"]

    def test_broken_override_falls_back_to_the_builtin(self):
        row = _row(subject="Approve {{ missing_field }}")
        email = run(template_store.render(_db(row), "approval_requested", APPROVAL))
        assert "approve 1200 INR software" in email.subject

    def test_sandbox_blocks_python_internals(self):
        row = _row(subject="x", body="{{ ''.__class__.__mro__[1].__subclasses__() }}")
        email = run(template_store.render(_db(row), "approval_requested", APPROVAL))
        assert "subclasses" not in email.body and "approve 1200 INR" in email.subject  # fell back

    def test_turned_off(self):
        email = run(template_store.render(_db(_row(enabled=False)), "approval_requested", APPROVAL))
        assert not email.enabled


class TestDispatcher:
    def _notify(self, rendered, priority="urgent"):
        send, record = AsyncMock(), AsyncMock()
        with patch.object(template_store, "render", AsyncMock(return_value=rendered)), \
             patch.object(dispatcher.email_service, "send_email", send), \
             patch.object(dispatcher.log_service, "record", record):
            run(dispatcher.notify(MagicMock(), event_type="approval.requested", template_name="approval_requested",
                                  context=APPROVAL, recipient="boss@acme.test", priority_override=priority))
        return send, record

    def test_extra_recipients_get_a_copy(self):
        send, record = self._notify(template_store.Rendered("S", "B", ["audit@acme.test"], True))
        assert [c.args[0] for c in send.await_args_list] == ["boss@acme.test", "audit@acme.test"]
        assert [c.kwargs["status"] for c in record.await_args_list] == ["sent", "sent"]

    def test_turned_off_template_is_logged_not_sent(self):
        send, record = self._notify(template_store.Rendered("", "", [], False))
        send.assert_not_awaited()
        assert record.await_args.kwargs["status"] == "skipped"

    def test_turned_off_template_is_not_queued_for_the_digest(self):
        enqueue, record = AsyncMock(), AsyncMock()
        with patch.object(template_store, "is_enabled", AsyncMock(return_value=False)), \
             patch.object(dispatcher.digest_service, "enqueue", enqueue), \
             patch.object(dispatcher.log_service, "record", record):
            run(dispatcher.notify(MagicMock(), event_type="goods.received", template_name="goods_received",
                                  context={}, recipient="r@acme.test", priority_override="digest"))
        enqueue.assert_not_awaited()
        assert record.await_args.kwargs["status"] == "skipped"


def _client(role):
    app = FastAPI()
    app.include_router(templates_api.router, prefix="/notifications/templates")
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id="u", email="a@acme.test", role=role)
    app.dependency_overrides[get_db] = lambda: _db(None)
    return TestClient(app)


class TestApi:
    @pytest.mark.parametrize("role", ["requester", "approver", "finance"])
    def test_only_admins(self, role):
        assert _client(role).get("/notifications/templates").status_code == 403

    def test_detail_has_default_and_placeholders(self):
        r = _client("admin").get("/notifications/templates/approval_requested")
        assert r.status_code == 200
        d = r.json()["data"]
        assert d["default"]["subject"] and "request_id" in d["placeholders"] and d["placeholders_fixed"]

    def test_invalid_edit_is_a_422_with_the_reason(self):
        r = _client("admin").put("/notifications/templates/approval_requested",
                                 json={"subject": "{{ nope }}", "body": "B"})
        assert r.status_code == 422 and "nope" in r.text

    def test_saved_by_comes_from_the_token(self):
        save = AsyncMock(return_value=template_store.Template(name="approval_requested", subject="S", body="B"))
        with patch.object(template_store, "save", save):
            r = _client("admin").put("/notifications/templates/approval_requested",
                                     json={"subject": "Approve {{ request_id }}", "body": "B",
                                           "updated_by": "someone-else@acme.test"})
        assert r.status_code == 200
        assert save.await_args.kwargs["updated_by"] == "a@acme.test"

    def test_preview_fills_sample_values(self):
        r = _client("admin").post("/notifications/templates/approval_requested/preview",
                                  json={"subject": "Approve {{ request_id }}", "body": "{{ amount }}"})
        assert r.json()["data"] == {"subject": "Approve [request_id]", "body": "[amount]"}

    def test_unknown_template_is_404(self):
        assert _client("admin").get("/notifications/templates/nope").status_code == 404
