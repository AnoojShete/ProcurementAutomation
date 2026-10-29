"""Financial standing from audited statements (VEND-1 Phase 2): five checks,
score = share passed; incomplete statements are not assessed."""
import asyncio
import os
import sys
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

from app.services.collectors import company_collectors as cc  # noqa: E402

# Hathway Cable and Datacom, consolidated, year ended 31 Mar 2026 (Rs crore),
# audited results filed 17 Apr 2026.
HATHWAY = {"total_equity": 4466.74, "profit_after_tax": 82.24, "current_assets": 2762.99,
           "current_liabilities": 689.61, "total_borrowings": 0.47, "audit_opinion": "unmodified",
           "going_concern_doubt": False}
NOW = datetime(2026, 10, 29, tzinfo=timezone.utc)


def collect(evidence):
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.first.return_value = evidence
    db.execute.return_value = result
    observed = AsyncMock()
    with patch.object(cc, "record_raw_response", AsyncMock(return_value=SimpleNamespace(id="raw"))), \
            patch.object(cc, "record_observation", observed):
        asyncio.run(cc.collect_financial(db, SimpleNamespace(id="v1", name="Hathway"), NOW))
    return observed.call_args.kwargs


def statement(meta, period_end=date(2026, 3, 31)):
    return SimpleNamespace(evidence_type="financial_statement", metadata_json=meta,
                           created_at=datetime(2026, 10, 29, tzinfo=timezone.utc), valid_from=period_end)


def test_hathway_passes_all_five_checks():
    score, checks, missing = cc.financial_statement_score(HATHWAY)
    assert (score, missing) == (1.0, [])
    assert [passed for _, passed, _ in checks] == [True] * 5


def test_each_failed_check_costs_a_fifth():
    weak = {**HATHWAY, "profit_after_tax": -5, "audit_opinion": "qualified"}
    assert cc.financial_statement_score(weak)[0] == 0.6


def test_going_concern_doubt_scores_zero():
    assert cc.financial_statement_score({**HATHWAY, "going_concern_doubt": True})[0] == 0.0


def test_statement_without_figures_is_not_assessed():
    # It used to score a default 0.85 (a pass) when finance typed no score.
    obs = collect(statement({}))
    assert obs["status"] == "not_checked"
    assert obs["fields"]["fin.basis"] == "none"
    assert any(f["label"] == "Statement incomplete" for f in obs["facts"])


def test_complete_statement_is_scored_and_explained():
    obs = collect(statement(HATHWAY))
    assert obs["fields"]["fin.basis"] == "score"
    assert obs["fields"]["fin.score"] == 1.0
    assert obs["fields"]["fin.evidence_age_days"] == 212
    assert any(f["label"] == "Profitable year" and f["value"].startswith("pass") for f in obs["facts"])


def test_statement_ages_from_its_period_end_not_the_upload():
    obs = collect(statement(HATHWAY, period_end=date(2025, 3, 31)))
    assert obs["fields"]["fin.basis"] == "none"
