"""compute_next_action for an approved request reads its contract through
this service's Contract stub. The stub had no `status`, so listing requests
(GET /requests/) and opening an approved request returned 500 (found 25 Oct
by demo_scenarios.py)."""
import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.api.requests import compute_next_action
from app.models import Contract


def _next_action(contract, role):
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=contract)))
    req = SimpleNamespace(id=str(uuid.uuid4()), status="approved", requested_by="requester@company.com")
    user = SimpleNamespace(role=role, email=f"{role}@company.com")
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(compute_next_action(db, req, user))
    finally:
        loop.close()


def test_draft_contract_offers_signing_to_finance():
    contract = Contract(id=str(uuid.uuid4()), status="draft")
    assert _next_action(contract, "finance")["key"] == "sign_now"


def test_no_contract_offers_generation():
    assert _next_action(None, "finance")["key"] == "generate_contract"


def test_bulk_eligibility_reports_a_refused_authority():
    """bulk_eligibility read auth.reason_code / reason_message, which
    AuthorityDecision doesn't have: listing requests as admin or finance
    returned 500 (found 25 Oct)."""
    from unittest.mock import patch
    from app.services import bulk_service
    from app.services.approval_authority import AuthorityDecision
    refused = AuthorityDecision(allowed=False, code="not_assigned", reason="Not assigned to this level")
    req = SimpleNamespace(id="r-1", amount=1000, currency="INR", status="pending_approval", request_type="hardware",
                          requested_by="requester@company.com", requested_by_user_id=None, budget_status="within",
                          approval_chain=["dept_manager"], current_approver_index=0, vendor_id=None, document_id=None)
    loop = asyncio.new_event_loop()
    try:
        with patch.object(bulk_service, "check_request_authority", AsyncMock(return_value=refused)):
            eligible, codes, labels = loop.run_until_complete(
                bulk_service.bulk_eligibility(AsyncMock(), req, "admin@company.com", "admin"))
    finally:
        loop.close()
    assert eligible is False and "not_assigned" in codes and "Not assigned to this level" in labels
