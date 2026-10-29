"""Risk page "parameters considered" view, and the feedback / incident
records the feedback and incidents parameters read (30 Oct 2026: nothing in
the app wrote them before, so both parameters could never be assessed)."""
import os
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

from app.api import vendors  # noqa: E402
from app.database import get_db  # noqa: E402
from shared.auth import get_current_user  # noqa: E402
from shared.auth.middleware import CurrentUser  # noqa: E402

NOW = datetime(2026, 10, 30, 9, 0, tzinfo=timezone.utc)


def _client(role="finance", db=None):
    app = FastAPI()
    app.include_router(vendors.router, prefix="/vendors")
    db = db or AsyncMock()
    if db.get.return_value is None or isinstance(db.get.return_value, AsyncMock):
        db.get.return_value = SimpleNamespace(id="v1", name="Kestrel Freight Systems Pvt Ltd")
    db.add = MagicMock()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id="u", email=f"{role}@x.test", role=role)
    return TestClient(app), db


def test_feedback_is_recorded_as_the_signed_in_user_and_bounded():
    c, db = _client()
    r = c.post("/vendors/v1/feedback", json={"overall_rating": 2, "dimension": "delivery",
                                            "rated_by": "someone-else@x.test"})
    assert r.status_code == 201
    entry = db.add.call_args.args[0]
    assert entry.entity_type == "vendor_feedback" and entry.payload["vendor_id"] == "v1"
    assert entry.payload["overall_rating"] == 2 and entry.payload["rated_by"] == "finance@x.test"
    assert c.post("/vendors/v1/feedback", json={"overall_rating": 6}).status_code == 422
    assert c.post("/vendors/v1/feedback", json={"overall_rating": 3, "dimension": "vibes"}).status_code == 422


def test_requesters_cannot_rate_or_report_incidents():
    c, _ = _client(role="requester")
    assert c.post("/vendors/v1/feedback", json={"overall_rating": 5}).status_code == 403
    assert c.post("/vendors/v1/incidents", json={"description": "Server room outage for six hours"}).status_code == 403


def test_incident_is_recorded_and_future_dates_refused():
    c, db = _client()
    r = c.post("/vendors/v1/incidents", json={"description": "Delivery lost in transit, replaced after 3 weeks",
                                             "occurred_on": "2026-10-01"})
    assert r.status_code == 201
    entry = db.add.call_args.args[0]
    assert entry.entity_type == "vendor_incident" and entry.payload["reported_by"] == "finance@x.test"
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=2)).date().isoformat()
    assert c.post("/vendors/v1/incidents", json={"description": "Something that has not happened yet",
                                                "occurred_on": tomorrow}).status_code == 400


@pytest.mark.asyncio
async def test_a_recorded_incident_counts_as_track_record_for_a_new_vendor():
    """A vendor onboarded last week with a major incident on file: the
    incidents parameter is assessed (+4), not "no track record yet"."""
    from app.services.collectors import performance_collectors as pc
    recorded = {}

    async def observation(**kw):
        recorded.update(kw)
        return SimpleNamespace(**kw)

    incident = SimpleNamespace(id="a1", created_at=NOW - timedelta(days=2), payload={"severity": "major"})
    db = AsyncMock()
    db.execute.side_effect = [MagicMock(scalar=MagicMock(return_value=0)),          # delivered orders
                              MagicMock(all=MagicMock(return_value=[incident]))]    # incidents
    vendor = SimpleNamespace(id="v1", created_at=NOW - timedelta(days=7))
    with patch.object(pc, "record_raw_response", AsyncMock(return_value=SimpleNamespace(id="raw"))), \
            patch.object(pc, "record_observation", observation):
        obs, _ = await pc.collect_incidents(db, vendor, NOW)
    assert recorded["fields"]["inc.history_available"] is True and recorded["fields"]["inc.count_24m"] == 1

    from app.services.scorecard.default_ruleset import get_default_ruleset
    from app.services.scorecard.engine import evaluate_risk
    res = evaluate_risk(get_default_ruleset(), {"incidents": obs}, NOW, vendor_context={"country": "IN"})
    inc = next(r for r in res["rule_results"] if r["signal_key"] == "incidents")
    assert inc["status"] == "assessed" and inc["points"] == 4


def test_risk_parameters_lists_every_parameter_with_weight_and_each_vendors_result():
    from app.services.scorecard.default_ruleset import get_default_ruleset
    vendor = SimpleNamespace(id="v1", name="Kestrel Freight Systems Pvt Ltd", country="IN", inherent_tier="critical",
                             created_at=NOW)
    score = SimpleNamespace(id="s1", final_band="Medium", band="Medium", rating_status="assessed", total_points=24,
                            scored_at=NOW, explanation={"weighted_points": 29, "checked_max_points": 82,
                                                        "headline": "Medium: 29/100."})
    rows = [SimpleNamespace(signal_key="certification", rule_id="R-CRT-05", status="assessed", points=4,
                            override_band=None, reason_text="No security certification on file."),
            SimpleNamespace(signal_key="delivery_sla", rule_id="R-SLA-01", status="not_assessed", points=0,
                            override_band=None, reason_text="0 delivered orders; at least 3 are needed.")]
    db = AsyncMock()
    db.execute.side_effect = [MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[vendor])))),
                              MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=rows))))]
    c, _ = _client(db=db)
    with patch.object(vendors.risk_service, "get_active_ruleset",
                      AsyncMock(return_value=SimpleNamespace(definition=get_default_ruleset()))), \
            patch.object(vendors.risk_service, "latest_risk_score", AsyncMock(return_value=score)):
        data = c.get("/vendors/risk-parameters").json()["data"]
    params = {p["key"]: p for p in data["parameters"]}
    assert len(params) == 14 and sum(p["max_points"] for p in params.values()) == 100
    assert params["certification"]["max_points"] == 4 and params["feedback"]["group"]
    row = data["vendors"][0]
    assert (row["final_band"], row["weighted_points"], row["checked_max_points"]) == ("Medium", 29, 82)
    assert row["parameters"]["certification"] == {"rule_id": "R-CRT-05", "status": "assessed", "points": 4,
                                                  "override": False, "reason": "No security certification on file."}
    assert row["parameters"]["delivery_sla"]["status"] == "not_assessed"
