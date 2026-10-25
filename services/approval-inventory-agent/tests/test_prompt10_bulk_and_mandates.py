import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.models import PurchaseRequest, EmailBatchToken
from app.services.bulk_service import bulk_eligibility, execute_bulk_decision
from app.services.email_action_token_service import mint_batch_action_token, hash_token


@pytest.fixture
def mock_db():
    db = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_bulk_eligibility_limits_and_segregation(mock_db):
    now = datetime.now(timezone.utc)
    approver_id = str(uuid.uuid4())
    approver_role = "approver"
    approver_email = "approver@company.com"

    # 1. Eligible request
    req1 = MagicMock(spec=PurchaseRequest)
    req1.id = str(uuid.uuid4())
    req1.amount = Decimal("15000")
    req1.currency = "INR"
    req1.status = "pending_approval"
    req1.requested_by = "requester@company.com"
    req1.request_type = "hardware"
    req1.over_budget = False
    req1.unmatched_invoice = False
    req1.approval_chain = ["dept_manager"]
    req1.current_approver_index = 0
    req1.vendor_id = None
    req1.document_id = None

    auth_mock = MagicMock()
    auth_mock.allowed = True

    with patch("app.services.bulk_service.get_rule", side_effect=lambda k, fallback: {
        "approval.bulk_approve_enabled": True,
        "approval.bulk_approve_max_amount": 25000.0,
        "approval.bulk_excluded_request_types": [],
    }.get(k, fallback)):
        with patch("app.services.bulk_service.check_request_authority", new=AsyncMock(return_value=auth_mock)):
            eligible, codes, labels = await bulk_eligibility(
                mock_db, req1, approver_id, approver_role, now
            )
            assert eligible is True
            assert len(codes) == 0

    # 2. Exceeds max amount -> Ineligible
    req2 = MagicMock(spec=PurchaseRequest)
    req2.id = str(uuid.uuid4())
    req2.amount = Decimal("30000")
    req2.currency = "INR"
    req2.status = "pending_approval"
    req2.requested_by = "requester@company.com"
    req2.request_type = "hardware"
    req2.over_budget = False
    req2.unmatched_invoice = False
    req2.approval_chain = ["dept_manager"]
    req2.current_approver_index = 0
    req2.vendor_id = None
    req2.document_id = None

    with patch("app.services.bulk_service.get_rule", side_effect=lambda k, fallback: {
        "approval.bulk_approve_enabled": True,
        "approval.bulk_approve_max_amount": 25000.0,
        "approval.bulk_excluded_request_types": [],
    }.get(k, fallback)):
        with patch("app.services.bulk_service.check_request_authority", new=AsyncMock(return_value=auth_mock)):
            eligible, codes, labels = await bulk_eligibility(
                mock_db, req2, approver_id, approver_role, now
            )
            assert eligible is False
            assert "above_bulk_limit" in codes

    # 3. Segregation of duties: requester == approver -> Ineligible
    req3 = MagicMock(spec=PurchaseRequest)
    req3.id = str(uuid.uuid4())
    req3.amount = Decimal("10000")
    req3.currency = "INR"
    req3.status = "pending_approval"
    req3.requested_by = approver_id
    req3.request_type = "hardware"
    req3.over_budget = False
    req3.unmatched_invoice = False
    req3.approval_chain = ["dept_manager"]
    req3.current_approver_index = 0
    req3.vendor_id = None
    req3.document_id = None

    with patch("app.services.bulk_service.get_rule", side_effect=lambda k, fallback: {
        "approval.bulk_approve_enabled": True,
        "approval.bulk_approve_max_amount": 25000.0,
        "approval.bulk_excluded_request_types": [],
    }.get(k, fallback)):
        with patch("app.services.bulk_service.check_request_authority", new=AsyncMock(return_value=auth_mock)):
            eligible, codes, labels = await bulk_eligibility(
                mock_db, req3, approver_id, approver_role, now
            )
            assert eligible is False
            assert "own_request" in codes


@pytest.mark.asyncio
async def test_mint_batch_action_token(mock_db):
    approver_id = "finance@company.com"
    request_ids = ["r-1", "r-2", "r-3"]

    with patch("app.services.email_action_token_service.get_rule", return_value=48):
        token_plain, token_hash, expires_at = await mint_batch_action_token(mock_db, approver_id, request_ids)
        assert token_plain is not None
        assert token_hash is not None
        assert expires_at is not None
        assert mock_db.add.called
        added_token = mock_db.add.call_args[0][0]
        assert isinstance(added_token, EmailBatchToken)
        assert added_token.approver_id == approver_id
        assert added_token.token_hash == hash_token(token_plain)
        assert added_token.request_ids == request_ids


@pytest.mark.asyncio
async def test_execute_bulk_decision_max_items_rejection(mock_db):
    exec_res = MagicMock()
    exec_res.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = exec_res
    approver_id = "approver@company.com"
    too_many_ids = [f"r-{i}" for i in range(30)]

    with patch("app.services.bulk_service.get_rule", side_effect=lambda k, fallback: {
        "approval.bulk_approve_max_items": 25,
    }.get(k, fallback)):
        with pytest.raises(Exception) as exc_info:
            await execute_bulk_decision(
                db=mock_db,
                producer=MagicMock(),
                approver_id=approver_id,
                approver_role="approver",
                request_ids=too_many_ids,
                idempotency_key="key-test-1",
            )
        assert "Cannot process more than" in str(exc_info.value)
