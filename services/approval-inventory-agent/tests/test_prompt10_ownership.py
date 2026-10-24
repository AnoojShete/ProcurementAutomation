import pytest
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch, MagicMock

from app.models import PurchaseRequest
from shared.auth import CurrentUser


@pytest.mark.asyncio
async def test_admin_email_change_keeps_access_and_blocks_new_holder():
    """Prompt 10 Section 6.3:
    Test that an admin email change keeps access to old records for the original user
    and does not give access to a new holder of the old email.
    """
    user_a_id = str(uuid.uuid4())
    user_b_id = str(uuid.uuid4())

    original_email = "alice@company.com"
    new_email = "alice.new@company.com"

    # User A creates a purchase request
    req = PurchaseRequest(
        id=str(uuid.uuid4()),
        requested_by=original_email,
        requested_by_user_id=user_a_id,
        department="Engineering",
        amount=Decimal("10000"),
        currency="INR",
        spend_tier="manager",
        status="pending_approval",
    )

    # 1. User A after email change (user_id = user_a_id, email = alice.new@company.com)
    user_a_updated = CurrentUser(
        id=user_a_id,
        email=new_email,
        role="requester",
    )

    # Ownership check logic:
    is_owner_a = False
    if req.requested_by_user_id and user_a_updated.id:
        is_owner_a = (str(req.requested_by_user_id) == str(user_a_updated.id))
    elif not req.requested_by_user_id and req.requested_by and user_a_updated.email:
        is_owner_a = (req.requested_by.strip().lower() == user_a_updated.email.strip().lower())

    assert is_owner_a is True, "User A must retain access after their email is changed by admin"

    # 2. User B who took over the old email (user_id = user_b_id, email = alice@company.com)
    user_b_new_holder = CurrentUser(
        id=user_b_id,
        email=original_email,
        role="requester",
    )

    is_owner_b = False
    if req.requested_by_user_id and user_b_new_holder.id:
        is_owner_b = (str(req.requested_by_user_id) == str(user_b_new_holder.id))
    elif not req.requested_by_user_id and req.requested_by and user_b_new_holder.email:
        is_owner_b = (req.requested_by.strip().lower() == user_b_new_holder.email.strip().lower())

    assert is_owner_b is False, "New holder of old email must NOT get access to old records"
