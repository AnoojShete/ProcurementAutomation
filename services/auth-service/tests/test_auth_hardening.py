"""Second audit pass: account identity and login timing. (The full flows,
against a real database, are in test_account_flows.py.)"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import auth
from app.database import get_db
from app.security import hash_password


def _db(existing_user=None):
    db = AsyncMock()
    res = MagicMock()
    res.scalars.return_value.first.return_value = existing_user
    db.execute.return_value = res
    db.add = MagicMock()
    return db


def _client(db):
    app = FastAPI()
    app.include_router(auth.router, prefix="/auth")
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


@pytest.fixture(autouse=True)
def no_lockout_table():
    with patch.object(auth.lockout, "locked_until", AsyncMock(return_value=None)), \
            patch.object(auth.lockout, "record_failure", AsyncMock(return_value=False)), \
            patch.object(auth.lockout, "clear", AsyncMock()), \
            patch.object(auth.audit, "record", AsyncMock()):
        yield


def _query_text(db) -> str:
    return " ".join(
        str(c.args[0].compile(compile_kwargs={"literal_binds": True})).lower()
        for c in db.execute.call_args_list if hasattr(c.args[0], "compile")
    )


class TestEmailIdentity:
    def test_login_matches_email_case_insensitively(self):
        user = SimpleNamespace(id="u1", email="alice@acme.example.com", role="requester", is_active=True,
                               email_verified_at="2026-01-01", token_version=0,
                               hashed_password=hash_password("a-long-enough-pass"))
        db = _db(user)
        r = _client(db).post("/auth/login", json={"email": "Alice@ACME.example.com", "password": "a-long-enough-pass"})
        assert r.status_code == 200
        assert "lower(" in _query_text(db) and "'alice@acme.example.com'" in _query_text(db)


class TestPasswords:
    def test_unknown_account_still_costs_a_hash_check(self):
        # Without it, "no such user" answered measurably faster than "wrong password".
        with patch.object(auth, "verify_password_dummy") as dummy:
            r = _client(_db(None)).post("/auth/login", json={"email": "nobody@acme.example.com", "password": "whatever-password"})
        assert r.status_code == 401
        dummy.assert_called_once()

    def test_overlong_passwords_rejected_before_hashing(self):
        with patch.object(auth, "is_password_breached", AsyncMock(return_value=False)), \
                patch.object(auth, "hash_password") as hasher:
            r = _client(_db(None)).post("/auth/register", json={"email": "x@acme.example.com", "password": "é" * 200})
        assert r.status_code == 400 and "128" in r.text
        hasher.assert_not_called()

    def test_breach_service_down_fails_closed(self):
        with patch.object(auth, "is_password_breached", AsyncMock(side_effect=OSError("offline"))):
            r = _client(_db(None)).post("/auth/register", json={"email": "x@acme.example.com", "password": "a-long-enough-pass"})
        assert r.status_code == 503
