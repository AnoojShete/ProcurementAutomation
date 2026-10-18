"""M7: demo-only simulated signing is off outside development."""
from app.config import Settings


def test_simulated_signatures_off_in_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    assert Settings().allow_simulated_signatures is False


def test_simulated_signatures_on_in_development(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    assert Settings().allow_simulated_signatures is True


def test_explicit_setting_wins(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("APP_ALLOW_SIMULATED_SIGNATURES", "true")
    assert Settings().allow_simulated_signatures is True
