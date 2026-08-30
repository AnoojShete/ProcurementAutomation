"""Exercises shared/audit/router.py's admin-gating and response shape
end-to-end (JWT issued via shared.auth.jwt_tokens, DB session mocked —
no live Postgres needed, matching this suite's pure-logic/no-live-infra
convention) rather than just unit-testing list_audit_log() in isolation.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import String, DateTime, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from shared.audit import build_audit_router
from shared.auth.jwt_tokens import create_access_token


class _Base(DeclarativeBase):
    pass


class FakeAuditRow(_Base):
    """A real (if minimal) mapped class — shared/audit/queries.py's
    select(model) requires one, same as the real per-service AuditLog
    models it's actually called with in production."""
    __tablename__ = "fake_audit_row"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String)
    entity_id: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def __init__(self):
        self.id = "row-1"
        self.entity_type = "document"
        self.entity_id = "doc-1"
        self.action = "human_review_correction"
        self.payload = {"reviewed_by": "alice"}
        self.created_at = datetime.now(timezone.utc)


def _build_app(mock_session):
    app = FastAPI()

    async def fake_get_db():
        yield mock_session

    app.include_router(build_audit_router(FakeAuditRow, fake_get_db, entity_types=["document"]))
    return app


def _mock_session_with_rows(rows):
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    session.execute = AsyncMock(return_value=result)
    return session


class TestAuditRouter:
    def test_requires_authentication(self):
        client = TestClient(_build_app(_mock_session_with_rows([])))
        resp = client.get("/audit")
        assert resp.status_code == 401

    def test_non_admin_forbidden(self):
        client = TestClient(_build_app(_mock_session_with_rows([])))
        token = create_access_token("u1", "requester@demo.example.com", "requester")
        resp = client.get("/audit", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403

    def test_admin_gets_shaped_response(self):
        client = TestClient(_build_app(_mock_session_with_rows([FakeAuditRow()])))
        token = create_access_token("u1", "admin@demo.example.com", "admin")
        resp = client.get("/audit", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["meta"]["count"] == 1
        row = body["data"][0]
        assert row["entity_type"] == "document"
        assert row["action"] == "human_review_correction"
        assert row["detail"] == {"reviewed_by": "alice"}
