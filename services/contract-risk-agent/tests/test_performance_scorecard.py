"""Feature expansion Phase 3c: vendor scorecards from the platform's own
records, and quiet when another service's table isn't there yet."""
import asyncio
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

from contextlib import asynccontextmanager  # noqa: E402

from app.services import performance_scorecard as scorecard  # noqa: E402


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _db(answers):
    """answers: substring of the SQL -> row (or an Exception to raise)."""
    db = MagicMock()

    @asynccontextmanager
    async def nested():
        yield
    db.begin_nested = nested

    async def execute(stmt, params=None):
        sql = str(stmt)
        for key, row in answers.items():
            if key in sql:
                if isinstance(row, Exception):
                    raise row
                return MagicMock(first=MagicMock(return_value=row))
        return MagicMock(first=MagicMock(return_value=None))
    db.execute = execute
    return db


SIGNALS = {"on_time_delivery_rate": 0.75, "deliveries": 4, "deliveries_on_time": 3, "expected_delivery_days": 14,
           "vendor_tenure_months": 6}


def test_scorecard_figures():
    db = _db({"invoice_matches": SimpleNamespace(clean=9, total=10), "rfq_invitations": SimpleNamespace(answered=1, total=4),
              "obligation_events": (2,), "risk_scores": ("Medium",)})
    with patch.object(scorecard, "platform_signals", AsyncMock(return_value=SIGNALS)):
        card = run(scorecard.compute(db, "v1"))
    assert (card["on_time_rate"], card["invoice_accuracy"], card["rfq_response_rate"], card["sla_breaches"], card["risk_band"]) == \
        (0.75, 0.9, 0.25, 2, "Medium")


def test_no_history_is_unknown_not_zero():
    db = _db({"invoice_matches": SimpleNamespace(clean=0, total=0), "rfq_invitations": SimpleNamespace(answered=0, total=0)})
    with patch.object(scorecard, "platform_signals", AsyncMock(return_value={**SIGNALS, "on_time_delivery_rate": None, "deliveries": 0})):
        card = run(scorecard.compute(db, "v1"))
    assert card["on_time_rate"] is None and card["invoice_accuracy"] is None and card["rfq_response_rate"] is None


def test_missing_tables_of_other_services_are_tolerated():
    db = _db({"rfq_invitations": Exception('relation "rfq_invitations" does not exist'),
              "obligation_events": Exception('relation "obligation_events" does not exist')})
    with patch.object(scorecard, "platform_signals", AsyncMock(return_value=SIGNALS)):
        card = run(scorecard.compute(db, "v1"))
    assert card["rfq_invitations"] == 0 and card["sla_breaches"] == 0
