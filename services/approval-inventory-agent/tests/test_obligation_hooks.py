"""Feature expansion Phase 2 hooks in this service: the invoice ledger
warns while an SLA credit is still expected, and licence reclaims stop at
the contract's minimum commitment. Both read contract-risk-agent's tables
and must keep working before those tables exist."""
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.services import invoice_ledger
from app.services.usage_service import UsageService


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _db(rows=None, first=None, fail=False):
    db = MagicMock()

    @asynccontextmanager
    async def nested():
        yield
    db.begin_nested = nested
    if fail:
        db.execute = AsyncMock(side_effect=Exception('relation "sla_credits" does not exist'))
    else:
        db.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=rows or []),
                                                      first=MagicMock(return_value=first)))
    return db


def test_expected_credit_is_noted_on_the_match():
    rows = [SimpleNamespace(id="c1", period="2026-09", credit_amount=1500, currency="INR"),
            SimpleNamespace(id="c2", period="2026-10", credit_amount=500, currency="INR")]
    notes = run(invoice_ledger.expected_credit_notes(_db(rows), "pr-1"))
    assert len(notes) == 1 and "INR 2,000.00" in notes[0] and "2026-09, 2026-10" in notes[0]


def test_no_note_without_expected_credits_or_before_the_table_exists():
    assert run(invoice_ledger.expected_credit_notes(_db([]), "pr-1")) == []
    assert run(invoice_ledger.expected_credit_notes(_db(fail=True), "pr-1")) == []


def test_contract_minimum_seats():
    assert run(UsageService.contract_minimum_seats(_db(first=(20,)), "l-1")) == 20
    assert run(UsageService.contract_minimum_seats(_db(first=(None,)), "l-1")) is None
    assert run(UsageService.contract_minimum_seats(_db(fail=True), "l-1")) is None
