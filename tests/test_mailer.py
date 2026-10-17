"""shared/mailer.py: provider switch, refusal of unsafe settings, and the
shape of every message (From/Reply-To, text + HTML)."""
from unittest.mock import MagicMock, patch

import pytest

from shared import mailer
from shared.runtime_env import InsecureConfigError

GMAIL = {
    "EMAIL_MODE": "smtp", "SMTP_HOST": "smtp.gmail.com", "SMTP_PORT": "587", "SMTP_SECURITY": "starttls",
    "SMTP_USERNAME": "someone@gmail.com", "SMTP_PASSWORD": "abcd efgh ijkl mnop",
    "EMAIL_FROM": "Procurement Platform <someone@gmail.com>", "EMAIL_REPLY_TO": "team@example.com",
    "APP_BASE_URL": "https://procure.example.com/",
}


@pytest.fixture
def env(monkeypatch):
    for k in list(GMAIL) + ["APP_ENV"]:
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


def test_dev_mode_is_mailpit(env):
    env.setenv("APP_ENV", "development")
    s = mailer.load_settings()
    assert (s.mode, s.host, s.port, s.security) == ("dev", "mailpit", 1025, "none")


def test_dev_mode_refused_in_production(env):
    env.setenv("APP_ENV", "production")
    with pytest.raises(InsecureConfigError):
        mailer.load_settings()


def test_gmail_settings(env):
    env.setenv("APP_ENV", "production")
    for k, v in GMAIL.items():
        env.setenv(k, v)
    s = mailer.load_settings()
    assert s.password == "abcdefghijklmnop"  # Gmail's display spaces removed
    assert s.app_base_url == "https://procure.example.com"


def test_empty_compose_values_mean_default(env):
    env.setenv("APP_ENV", "development")
    env.setenv("SMTP_PORT", "")
    env.setenv("SMTP_HOST", "")
    assert mailer.load_settings().port == 1025


@pytest.mark.parametrize("override", [
    {"SMTP_PASSWORD": ""}, {"SMTP_HOST": ""}, {"SMTP_USERNAME": ""},
    {"SMTP_SECURITY": "none"},          # credentials in clear text
    {"EMAIL_FROM": "no address here"},
    {"EMAIL_MODE": "carrier-pigeon"},
])
def test_incomplete_real_settings_refused(env, override):
    env.setenv("APP_ENV", "production")
    for k, v in {**GMAIL, **override}.items():
        env.setenv(k, v)
    with pytest.raises((mailer.MailConfigError, InsecureConfigError)):
        mailer.load_settings()


def _settings(**kw):
    base = dict(mode="smtp", host="smtp.gmail.com", port=587, security="starttls", username="u",
                password="p", email_from="Procurement Platform <someone@gmail.com>",
                reply_to="team@example.com", app_base_url="https://x")
    return mailer.MailSettings(**{**base, **kw})


def test_message_has_text_and_html_and_headers():
    msg = mailer.build_message(_settings(), "you@example.com", "Hello", "plain body", "<p>html body</p>")
    assert msg["From"] == "Procurement Platform <someone@gmail.com>"
    assert msg["Reply-To"] == "team@example.com"
    assert msg["Message-ID"].endswith("@gmail.com>")
    assert msg["Auto-Submitted"] == "auto-generated"
    assert msg.get_content_type() == "multipart/alternative"
    parts = [p.get_content_type() for p in msg.iter_parts()]
    assert parts == ["text/plain", "text/html"]  # text first = fallback


def test_no_reply_to_header_when_unset():
    assert "Reply-To" not in mailer.build_message(_settings(reply_to=""), "a@b.com", "s", "t")


@pytest.mark.parametrize("security,cls", [("starttls", "SMTP"), ("ssl", "SMTP_SSL")])
def test_transport_uses_tls_and_logs_in(security, cls):
    server = MagicMock()
    with patch.object(mailer.smtplib, cls, return_value=server) as ctor:
        mailer._send_blocking(_settings(security=security), mailer.build_message(_settings(), "a@b.com", "s", "t"))
    ctor.assert_called_once()
    inner = server
    assert server.__exit__.called  # connection closed
    assert inner.starttls.called == (security == "starttls")
    inner.login.assert_called_once_with("u", "p")
    inner.send_message.assert_called_once()


def test_env_example_works_as_is_on_a_fresh_clone(env):
    # install.sh copies .env.example to .env on a fresh clone. Its email
    # settings must give a working Mailpit setup untouched (it once set
    # SMTP_PORT=587 / starttls, so every account email was refused).
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    for line in (root / ".env.example").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            if key.startswith(("SMTP_", "EMAIL_")) or key == "APP_BASE_URL":
                env.setenv(key, value)
    env.setenv("APP_ENV", "development")
    s = mailer.load_settings()
    assert (s.mode, s.host, s.port, s.security) == ("dev", "mailpit", 1025, "none")
