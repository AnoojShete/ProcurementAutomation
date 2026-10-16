"""FR-13: Legal-BERT finds the clause passages, the parsers turn them into
values, and the regex rules take over when the model is missing or fails."""
import asyncio
import os
import sys
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

from app.services import clause_router  # noqa: E402
from app.services.clause_extraction import end_date_from, notice_days_from, renewal_type_from  # noqa: E402

CONTRACT = """4. TERM AND RENEWAL
   This agreement has a contract end date of 2027-03-15.
   This subscription shall renew automatically (auto-renew) for successive
   12-month terms unless either party gives written notice of
   non-renewal at least 60 days prior to the contract end date."""


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def route(**patches):
    with patch.object(clause_router, "_log_to_db", lambda *a: None), \
            patch.object(clause_router, "_fallback_forced", return_value=False):
        ctx = [patch.object(clause_router.clause_model, k, v) for k, v in patches.items()]
        for c in ctx:
            c.start()
        try:
            return run(clause_router.route_clause_extraction(MagicMock(), "c-1", CONTRACT))
        finally:
            for c in ctx:
                c.stop()


def passages(**texts):
    return {f: ({"text": t, "start": 0, "end": len(t), "score": 5.0} if t else None) for f, t in texts.items()}


def test_model_passages_become_values():
    found = passages(renewal_type="This subscription shall renew automatically (auto-renew) for successive 12-month terms",
                     notice_period_days="written notice of non-renewal at least 60 days prior to the contract end date",
                     contract_end_date="This agreement has a contract end date of 2027-03-15.")
    r = route(available=lambda: True, find_passages=lambda text: found)
    assert r.route_name == "legal_bert_primary" and r.model_used == "legal-bert-cuad"
    assert r.clauses == {"renewal_type": "auto", "notice_period_days": 60, "contract_end_date": date(2027, 3, 15)}


def test_no_model_downloaded_uses_the_rules():
    r = route(available=lambda: False)
    assert r.route_name == "regex_fallback" and r.fallback_reason == "model_unavailable"
    assert r.clauses["notice_period_days"] == 60 and r.clauses["renewal_type"] == "auto"


def test_a_model_error_uses_the_rules():
    def boom(text):
        raise RuntimeError("out of memory")
    r = route(available=lambda: True, find_passages=boom)
    assert r.route_name == "regex_fallback" and r.fallback_reason == "exception"
    assert r.clauses["contract_end_date"] == date(2027, 3, 15)


@pytest.mark.parametrize("text,days", [
    ("written notice at least sixty (60) days prior to the end of the term", 60),
    ("notice must be given not less than fifteen (15) days before the end", 15),
    ("unless either party gives three (3) months' prior written notice", 90),
    ("renews for two (2) years unless notice is given 30 days before expiry", 30),
    ("This Agreement shall automatically renew for one year.", None),
])
def test_notice_days_from(text, days):
    assert notice_days_from(text) == days


@pytest.mark.parametrize("text,kind", [
    ("shall automatically renew for successive one (1) year terms", "auto"),
    ("This agreement does not automatically renew (manual renew)", "manual"),
    ("may be renewed for a further term by mutual written agreement", "manual"),
    (None, None),
])
def test_renewal_type_from(text, kind):
    assert renewal_type_from(text) == kind


@pytest.mark.parametrize("text,when", [
    ("commence on April 1, 1999 and expire on March 31, 2002", date(2002, 3, 31)),
    ("continue until the 31st day of December, 2025", date(2025, 12, 31)),
    ("for a period of five (5) years from the Effective Date", None),
])
def test_end_date_from(text, when):
    assert end_date_from(text) == when


def test_generated_contract_keeps_the_terms_it_was_written_with():
    """The notice period and end date are written into the contract by us;
    a misreading extractor must not change them — the disagreement goes to
    the audit log instead."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app.services import contract_service

    misread = clause_router.ClauseRoutingResult(
        route_name="legal_bert_primary", model_used="legal-bert-cuad", fallback_triggered=False,
        fallback_reason=None, confidence=1.0, duration_ms=1.0,
        clauses={"renewal_type": "auto", "notice_period_days": 90, "contract_end_date": date(2030, 1, 1)},
    )
    pr = SimpleNamespace(id="pr-1", vendor_id=None, department="IT", items=[], amount=1000, currency="INR",
                         requested_by="req@x")
    db = MagicMock()
    db.get = AsyncMock(return_value=pr)
    db.commit, db.refresh = AsyncMock(), AsyncMock()
    audit = AsyncMock()
    with patch.object(clause_router, "route_clause_extraction", AsyncMock(return_value=misread)), \
            patch.object(contract_service, "write_audit_log", audit), \
            patch.object(contract_service, "staged", return_value=None), \
            patch.object(contract_service, "start_renewal_workflow", AsyncMock()), \
            patch.object(contract_service, "load_config", return_value={"renewal": {"default_notice_period_days": 30}}):
        contract = run(contract_service.generate_contract_for_request(db, None, "pr-1", "saas_subscription"))
    assert contract.notice_period_days == 30
    assert contract.contract_end_date != date(2030, 1, 1)
    assert contract.renewal_type == "auto"
    details = audit.await_args.args[4]
    assert set(details["clause_mismatches"]) == {"notice_period_days", "contract_end_date"}
