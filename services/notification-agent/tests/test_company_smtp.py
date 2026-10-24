"""Tests for Custom Company SMTP settings, AES-256-GCM encryption,
admin-only API endpoints, and mailer integration.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.security.encryption import EncryptionService, default_encryption_service
from app.models import Base, CompanySmtpSettings
from app.main import app
from app.database import get_db
from app.services import email_service
from shared.auth.jwt_tokens import create_access_token


# --- 1. Encryption Service Tests ---

def test_encryption_roundtrip():
    service = EncryptionService()
    secret_text = "My_Super_Secret_SMTP_Password_2026!#"
    cipher = service.encrypt(secret_text)

    assert cipher is not None
    assert cipher.startswith("v2:") or cipher.startswith("v1:")

    decrypted = service.decrypt(cipher)
    assert decrypted == secret_text


def test_encryption_tamper_detection():
    service = EncryptionService()
    cipher = service.encrypt("ConfidentialPassword")
    assert cipher is not None

    tampered_cipher = cipher[:-4] + "AAAA"

    # Must return None (fail secure) on authentication tag mismatch
    assert service.decrypt(tampered_cipher) is None


def test_encryption_payload_too_short():
    service = EncryptionService()
    short_cipher = "v1:AAAA"
    assert service.decrypt(short_cipher) is None


def test_encryption_empty_and_none():
    service = EncryptionService()
    assert service.encrypt("") == ""
    assert service.encrypt(None) is None
    assert service.decrypt("") == ""
    assert service.decrypt(None) is None


# --- 2. API Endpoint & Access Control Tests ---

class MockAsyncDb:
    def __init__(self):
        self.rows = {}

    async def execute(self, stmt):
        class Result:
            def __init__(self, item):
                self._item = item
            def scalar_one_or_none(self):
                return self._item
        comp_id = 1
        item = self.rows.get(comp_id)
        return Result(item)

    def add(self, entity):
        self.rows[entity.comp_id] = entity

    async def commit(self):
        pass


@pytest.fixture
def mock_db():
    return MockAsyncDb()


@pytest.fixture
def admin_token():
    return create_access_token("admin-1", "admin@procurement.local", "admin")


@pytest.fixture
def requester_token():
    return create_access_token("req-1", "req@procurement.local", "requester")


def test_admin_only_access(mock_db, requester_token, admin_token):
    app.dependency_overrides[get_db] = lambda: mock_db
    client = TestClient(app)

    # 1. Unauthenticated: 401
    res = client.get("/smtp/GetSettings")
    assert res.status_code == 401

    # 2. Non-admin (requester): 403 Forbidden
    res = client.get(
        "/smtp/GetSettings",
        headers={"Authorization": f"Bearer {requester_token}"},
    )
    assert res.status_code == 403

    # 3. Admin: 200 OK
    res = client.get(
        "/smtp/GetSettings",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200
    assert res.json()["hasPassword"] is False

    app.dependency_overrides.clear()


def test_save_and_get_settings(mock_db, admin_token):
    app.dependency_overrides[get_db] = lambda: mock_db
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {admin_token}"}

    # 1. Save new settings
    save_payload = {
        "host": "smtp.company.com",
        "port": 587,
        "emailFrom": "procure@company.com",
        "username": "procure_user",
        "password": "InitialPassword123",
        "enableSsl": True,
        "companyId": 1,
    }
    res = client.post("/smtp/SaveSettings", json=save_payload, headers=headers)
    assert res.status_code == 200
    assert res.json()["success"] is True

    # 2. Get settings: password must be masked, hasPassword=True
    res = client.get("/smtp/GetSettings", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["host"] == "smtp.company.com"
    assert data["port"] == 587
    assert data["emailFrom"] == "procure@company.com"
    assert data["username"] == "procure_user"
    assert data["enableSsl"] is True
    assert data["hasPassword"] is True
    assert "password" not in data or data.get("password") is None

    # 3. Save again with blank password -> existing encrypted password preserved
    update_payload = {
        "host": "smtp.newhost.com",
        "port": 465,
        "emailFrom": "procure@newhost.com",
        "username": "new_user",
        "password": "",  # Blank: keep existing
        "enableSsl": True,
        "companyId": 1,
    }
    res = client.post("/smtp/SaveSettings", json=update_payload, headers=headers)
    assert res.status_code == 200

    # Verify DB still has encrypted password
    res = client.get("/smtp/GetSettings", headers=headers)
    data = res.json()
    assert data["host"] == "smtp.newhost.com"
    assert data["port"] == 465
    assert data["hasPassword"] is True

    app.dependency_overrides.clear()


def test_test_connection_endpoint(mock_db, admin_token):
    app.dependency_overrides[get_db] = lambda: mock_db
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {admin_token}"}

    test_payload = {
        "host": "smtp.gmail.com",
        "port": 587,
        "emailFrom": "admin@procurement.local",
        "username": "admin@procurement.local",
        "password": "test_app_password",
        "enableSsl": True,
        "companyId": 1,
    }

    with patch("app.api.smtp_settings._send_test_email_sync") as mock_send:
        res = client.post("/smtp/TestConnection", json=test_payload, headers=headers)
        assert res.status_code == 200
        assert res.json()["success"] is True
        assert "Test email sent to" in res.json()["message"]
        mock_send.assert_called_once()

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_email_service_custom_smtp_dispatch():
    mock_db = MockAsyncDb()
    encrypted_pw = default_encryption_service.encrypt("SecretCustomPassword")
    settings_row = CompanySmtpSettings(
        comp_id=1,
        host="custom.mailserver.com",
        port=587,
        email_from="notifications@customdomain.com",
        username="custom_user",
        password=encrypted_pw,
        enable_ssl=True,
        is_active=1,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    mock_db.add(settings_row)

    with patch("app.services.email_service.shared_send_email") as mock_mailer:
        await email_service.send_email(
            to="recipient@example.com",
            subject="Test Subject",
            body="Hello custom mailer",
            db=mock_db,
        )

        mock_mailer.assert_called_once()
        _, kwargs = mock_mailer.call_args
        assert kwargs["to"] == "recipient@example.com"
        assert kwargs["subject"] == "Test Subject"
        assert kwargs["text"] == "Hello custom mailer"

        mail_settings = kwargs["settings"]
        assert mail_settings is not None
        assert mail_settings.host == "custom.mailserver.com"
        assert mail_settings.port == 587
        assert mail_settings.username == "custom_user"
        assert mail_settings.password == "SecretCustomPassword"
        assert mail_settings.email_from == "notifications@customdomain.com"
