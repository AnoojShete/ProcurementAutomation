import os
import pytest
from fastapi import HTTPException
from app.api.smtp_settings import validate_smtp_host, normalize_smtp_host


def test_normalize_smtp_host():
    assert normalize_smtp_host("  smtp.gmail.com  ") == "smtp.gmail.com"
    assert normalize_smtp_host("google.com") == "smtp.gmail.com"
    assert normalize_smtp_host("SMTP.GOOGLE.COM") == "smtp.gmail.com"
    assert normalize_smtp_host("  MAIL.example.com ") == "mail.example.com"


def test_reject_loopback_and_private_ips(monkeypatch):
    monkeypatch.delenv("ALLOW_PRIVATE_SMTP", raising=False)

    disallowed = [
        "127.0.0.1",
        "127.0.0.50",
        "localhost",
        "10.0.0.1",
        "192.168.1.1",
        "172.16.0.1",
        "169.254.1.1",
        "::1",
    ]
    for host in disallowed:
        with pytest.raises(HTTPException) as exc_info:
            validate_smtp_host(host)
        assert exc_info.value.status_code == 400
        assert "disallowed private or loopback" in exc_info.value.detail


def test_allow_private_smtp_flag(monkeypatch):
    monkeypatch.setenv("ALLOW_PRIVATE_SMTP", "true")
    assert validate_smtp_host("127.0.0.1") == "127.0.0.1"
    assert validate_smtp_host("192.168.1.5") == "192.168.1.5"
    assert validate_smtp_host("localhost") == "localhost"
