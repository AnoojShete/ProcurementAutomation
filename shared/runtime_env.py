"""Which environment a service runs in, and what that allows.

APP_ENV defaults to "production": anything demo-only (seeded demo accounts,
simulated e-signatures, showcase scenario endpoints) and any well-known
default secret has to be opted into by setting APP_ENV=development, which
the demo docker-compose stack does. A deployment that forgets to configure
anything therefore fails closed instead of running with published secrets.
"""
import os

DEVELOPMENT_NAMES = frozenset({"development", "dev", "local", "test"})


class InsecureConfigError(RuntimeError):
    pass


def app_env() -> str:
    return os.environ.get("APP_ENV", "production").strip().lower()


def is_development() -> bool:
    return app_env() in DEVELOPMENT_NAMES


def require_secret(name: str, value: str | None, known_defaults: set[str]) -> None:
    """Refuse to run outside development with a missing or published secret."""
    if is_development():
        return
    if not value or value in known_defaults:
        raise InsecureConfigError(
            f"{name} is unset or set to a published default. Set a real secret, "
            f"or APP_ENV=development for a local demo."
        )
