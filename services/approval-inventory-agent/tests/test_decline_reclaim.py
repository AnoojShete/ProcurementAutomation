"""POST /requests/{id}/decline-reclaim on a license reclaim: the license
gets a cooldown so it isn't reclaimed again straight away. This path used
get_rule without importing it, so every decline of a license reclaim
raised NameError (found by the docs-audit lint pass, Sep 27)."""
import sys
import types
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.approval_service import ApprovalService


@pytest.mark.asyncio
async def test_declining_a_license_reclaim_sets_the_cooldown():
    license_row = SimpleNamespace(id="lic-1", reclaim_cooldown_until=None)
    req = SimpleNamespace(id="req-1", request_type="reclaim", status="pending_grace_period",
                          items=[{"license_id": "lic-1"}])
    db = AsyncMock()
    db.add = MagicMock()
    found = MagicMock()
    found.scalar_one_or_none.return_value = license_row
    db.execute.return_value = found

    service = ApprovalService(db, MagicMock(), MagicMock())
    service.get_request_with_history = AsyncMock(return_value=req)
    # No Temporal in unit tests: the signal attempt fails and is ignored.
    fake_temporal = types.ModuleType("temporalio.client")
    fake_temporal.Client = MagicMock(connect=AsyncMock(side_effect=ConnectionError("no temporal")))
    with patch.dict(sys.modules, {"temporalio.client": fake_temporal}), \
            patch("shared.rules_engine.get_rule", return_value=30):
        await service.decline_reclaim("req-1", "user@example.com")

    assert req.status == "cancelled"
    assert license_row.reclaim_cooldown_until is not None
    days = (license_row.reclaim_cooldown_until - datetime.now(timezone.utc)).days
    assert 29 <= days <= 30
