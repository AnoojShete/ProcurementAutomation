"""QA audit (Oct 17): requesters have a Notifications page and bell, but the
log was staff-only, so both failed with 403. Requesters now see only
notifications addressed to them — the recipient comes from the JWT, never
the query string. Staff still search everything.
(docs/quality-audit-report.md QA-07, QA-05)"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import notifications
from app.database import get_db
from app.services import log_service
from shared.auth import get_current_user
from shared.auth.middleware import CurrentUser


def _client(role, email="alice@acme.test"):
    app = FastAPI()
    app.include_router(notifications.router, prefix="/notifications")
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id="u", email=email, role=role)
    app.dependency_overrides[get_db] = lambda: MagicMock()
    return TestClient(app)


@pytest.fixture
def search():
    with patch.object(log_service, "search", AsyncMock(return_value=[])) as s:
        yield s


def test_requester_sees_only_own_notifications(search):
    r = _client("requester").get("/notifications/log?limit=20")
    assert r.status_code == 200
    assert search.await_args.kwargs["recipient"] == "alice@acme.test"


def test_requester_cannot_read_someone_elses_by_query(search):
    _client("requester").get("/notifications/log?recipient=procurement-ops@example.com")
    assert search.await_args.kwargs["recipient"] == "alice@acme.test"


@pytest.mark.parametrize("role", ["approver", "finance", "admin"])
def test_staff_search_the_whole_log(search, role):
    _client(role).get("/notifications/log?recipient=procurement-ops@example.com")
    assert search.await_args.kwargs["recipient"] == "procurement-ops@example.com"
    _client(role).get("/notifications/log")
    assert search.await_args.kwargs["recipient"] is None


@pytest.mark.parametrize("limit", [-1, 0, 1001])
def test_out_of_range_limit_is_a_422(search, limit):
    assert _client("admin").get(f"/notifications/log?limit={limit}").status_code == 422
    search.assert_not_awaited()
