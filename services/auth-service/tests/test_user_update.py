import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pydantic import ValidationError
from fastapi import HTTPException

from app.schemas import UserUpdateRequest, DemoAccountResponse
from app.security import normalize_email


def test_user_update_request_validation():
    # Valid email
    req = UserUpdateRequest(email="new.email@example.com", role="approver")
    assert req.email == "new.email@example.com"
    assert req.role == "approver"

    # None email is allowed
    req_no_email = UserUpdateRequest(role="admin")
    assert req_no_email.email is None

    # Invalid email raises validation error
    with pytest.raises(ValidationError):
        UserUpdateRequest(email="not-an-email")


def test_normalize_email():
    assert normalize_email("  Test.User@Example.COM ") == "test.user@example.com"
    assert normalize_email("") == ""
    assert normalize_email(None) == ""


@pytest.mark.asyncio
async def test_update_user_email_duplicate_rejected():
    from app.api.users import update_user
    from app.models import User
    from shared.auth.middleware import CurrentUser

    admin_user = CurrentUser(id="admin-id", email="admin@example.com", role="admin")
    target_user = User(
        id="target-id",
        email="old@example.com",
        role="requester",
        is_active=True,
        token_version=1,
        theme="system",
    )
    existing_other_user = User(
        id="other-id",
        email="taken@example.com",
        role="finance",
        is_active=True,
        token_version=0,
        theme="system",
    )

    db = AsyncMock()

    # First call finds target_user, second call finds existing_other_user
    result_mock1 = MagicMock()
    result_mock1.scalars.return_value.first.return_value = target_user

    result_mock2 = MagicMock()
    result_mock2.scalars.return_value.first.return_value = existing_other_user

    db.execute.side_effect = [result_mock1, result_mock2]

    req = UserUpdateRequest(email="taken@example.com")
    with pytest.raises(HTTPException) as exc_info:
        await update_user("target-id", req, admin=admin_user, db=db)

    assert exc_info.value.status_code == 400
    assert "already exists" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_update_user_email_success():
    from app.api.users import update_user
    from app.models import User
    from shared.auth.middleware import CurrentUser

    admin_user = CurrentUser(id="admin-id", email="admin@example.com", role="admin")
    target_user = User(
        id="target-id",
        email="old@example.com",
        role="requester",
        is_active=True,
        token_version=1,
        theme="system",
    )

    db = AsyncMock()

    # First call: find target_user; Second call: uniqueness check (returns None -> no conflict)
    result_mock1 = MagicMock()
    result_mock1.scalars.return_value.first.return_value = target_user

    result_mock2 = MagicMock()
    result_mock2.scalars.return_value.first.return_value = None

    db.execute.side_effect = [result_mock1, result_mock2]

    with patch("app.account_tokens.revoke_all", new_callable=AsyncMock) as mock_revoke, \
         patch("app.lockout.clear", new_callable=AsyncMock) as mock_clear, \
         patch("app.audit.record", new_callable=AsyncMock) as mock_audit:

        req = UserUpdateRequest(email="new@example.com")
        res = await update_user("target-id", req, admin=admin_user, db=db)

        assert target_user.email == "new@example.com"
        assert target_user.token_version == 2
        assert res.data.email == "new@example.com"

        # Check token revocation
        assert mock_revoke.call_count == 2
        # Check lockout clearing (for old and new email)
        assert mock_clear.call_count == 2
        # Check audit recording
        mock_audit.assert_called_once()
        db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_demo_accounts_endpoint():
    from app.api.auth import list_demo_accounts
    from app.models import User

    db = AsyncMock()
    demo_users = [
        User(id="1", email="admin@demo.example.com", role="admin", display_name="Anjali", is_active=True, theme="system"),
        User(id="2", email="finance@demo.example.com", role="finance", display_name="Niraj", is_active=True, theme="system"),
        User(id="3", email="requester@demo.example.com", role="requester", display_name="Anooj", is_active=True, theme="system"),
        User(id="4", email="approver@demo.example.com", role="approver", display_name="Vaidehi", is_active=True, theme="system"),
    ]

    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = demo_users
    db.execute.return_value = result_mock

    res = await list_demo_accounts(db=db)
    data = res.data
    assert len(data) == 4
    roles = [d.role for d in data]
    assert roles == ["admin", "finance", "requester", "approver"]
    emails = [d.email for d in data]
    assert "admin@demo.example.com" in emails
