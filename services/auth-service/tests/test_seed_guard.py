"""H4: demo accounts (published password, admin included) are only seeded
in development or when explicitly requested."""
import seed_demo_users


def test_not_seeded_in_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("SEED_DEMO_USERS", raising=False)
    assert seed_demo_users.should_seed() is False


def test_not_seeded_when_app_env_unset(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("SEED_DEMO_USERS", raising=False)
    assert seed_demo_users.should_seed() is False


def test_seeded_in_development_or_on_request(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    assert seed_demo_users.should_seed() is True
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SEED_DEMO_USERS", "true")
    assert seed_demo_users.should_seed() is True
