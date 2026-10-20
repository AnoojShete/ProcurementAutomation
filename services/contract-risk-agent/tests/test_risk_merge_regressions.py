"""Defects found when the deterministic risk scorecard (updated_risk) was
merged into anjali and run against a real database. Each test failed
before its fix."""
import asyncio
import glob
import os
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_migrations_do_not_write_business_rules():
    """auth-service owns business_rules. A contract-risk migration inserted
    into it with columns that don't exist (key/value), so the service could
    not start, and would have overwritten vendor.petty_tier_max_amount."""
    for path in glob.glob(os.path.join(HERE, "..", "migrations", "versions", "*.py")):
        code = "\n".join(l for l in open(path).read().splitlines() if not l.strip().startswith("#"))
        assert "INSERT INTO business_rules" not in code, os.path.basename(path)


def test_alembic_revisions_form_one_chain():
    """Both branches had added 0008 and 0009; the merge renumbered the
    scorecard migrations to 0010/0011."""
    import re
    revs, downs = {}, set()
    for path in glob.glob(os.path.join(HERE, "..", "migrations", "versions", "*.py")):
        text = open(path).read()
        rev = re.search(r'^revision = "([^"]+)"', text, re.M).group(1)
        down = re.search(r'^down_revision = (?:"([^"]+)"|None)', text, re.M).group(1)
        assert rev not in revs, f"duplicate revision {rev}"
        revs[rev] = down
        downs.add(down)
    heads = set(revs) - downs
    assert len(heads) == 1, f"more than one head: {heads}"


def test_weekly_monitoring_report_builds_its_queries():
    """func.sum(func.cast(cond, func.literal(1))) raised while the query was
    built, so GET /vendors/risk-monitoring/weekly-report was always a 500."""
    from app.services.scorecard import monitoring
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[]), scalar=MagicMock(return_value=0),
                                                  scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))
    report = run(monitoring.generate_monitoring_report(db))
    assert isinstance(report, dict)


def test_remediation_plan_builds_its_query():
    """.order_index(...) instead of .order_by(...): the remediation plan was always a 500."""
    from app.api import vendors as api
    score = SimpleNamespace(id="s1", ruleset_id=None, total_points=0, final_band="Unrated", band="Unrated",
                            rating_status="provisional", blocked_by=[], effective_tier="standard", snapshot={},
                            scored_at=datetime(2026, 10, 20, tzinfo=timezone.utc))
    db = MagicMock()
    db.get = AsyncMock(return_value=SimpleNamespace(id="v1"))
    db.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))
    with patch.object(api.risk_service, "latest_risk_score", AsyncMock(return_value=score)), \
            patch.object(api.risk_service, "get_active_ruleset", AsyncMock(return_value=SimpleNamespace(definition={"signals": [], "bands": {}}))), \
            patch.object(api, "build_remediation_plan", MagicMock(side_effect=lambda **kw: kw["assessment"])):
        plan = run(api.get_remediation_plan("v1", audience="internal", db=db)).data
    assert plan["rating_status"] == "provisional"      # passed through to the plan (was null)
