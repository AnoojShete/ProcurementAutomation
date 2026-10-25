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


def test_user_lookup_reads_auth_services_table():
    """UserRef pointed at a "users" table that doesn't exist; the failed query
    aborted the transaction, so approval and contract emails were never sent
    (found 25 Oct by invoice_lifecycle.py)."""
    import os
    import re
    auth_models = os.path.join(os.path.dirname(__file__), "../../auth-service/app/models.py")
    if os.path.exists(auth_models):
        assert UserRef.__tablename__ in re.findall(r'__tablename__ = "([a-z_]+)"', open(auth_models).read())
    assert UserRef.__tablename__ == "auth_users"
