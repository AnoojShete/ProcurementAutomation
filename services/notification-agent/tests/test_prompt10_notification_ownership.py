import pytest
import uuid
from unittest.mock import AsyncMock

from app.models import PurchaseRequestRef, UserRef
from app.services.directory import requester_for_request_id


@pytest.mark.asyncio
async def test_notification_routing_resolves_to_new_email_via_user_id():
    """Prompt 10 Section 6.3:
    Test notification routing uses user_id to look up the current email in UserRef.
    """
    user_id = str(uuid.uuid4())
    req_id = str(uuid.uuid4())

    db_mock = AsyncMock()

    pr_row = PurchaseRequestRef(
        id=req_id,
        requested_by="old.email@company.com",
        requested_by_user_id=user_id,
    )

    user_row = UserRef(
        id=user_id,
        email="updated.email@company.com",
    )

    async def mock_get(model, pk):
        if model == PurchaseRequestRef and pk == req_id:
            return pr_row
        if model == UserRef and pk == user_id:
            return user_row
        return None

    db_mock.get.side_effect = mock_get

    resolved_email = await requester_for_request_id(db_mock, req_id)
    assert resolved_email == "updated.email@company.com", "Notification must route to current email resolved via user_id"
