"""Security audit (Sep 26): configuration that must fail closed."""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from shared import idempotency
from shared.runtime_env import InsecureConfigError, require_secret

ROOT = Path(__file__).resolve().parent.parent


def test_default_secret_refused_in_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(InsecureConfigError):
        require_secret("JWT_SECRET", "dev-jwt-secret-change-me", {"dev-jwt-secret-change-me"})
    with pytest.raises(InsecureConfigError):
        require_secret("JWT_SECRET", "", {"x"})
    require_secret("JWT_SECRET", "a-real-secret", {"dev-jwt-secret-change-me"})


def test_unset_app_env_is_production(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    with pytest.raises(InsecureConfigError):
        require_secret("JWT_SECRET", "dev-jwt-secret-change-me", {"dev-jwt-secret-change-me"})


def test_development_allows_demo_defaults(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    require_secret("JWT_SECRET", "dev-jwt-secret-change-me", {"dev-jwt-secret-change-me"})


def test_jwt_config_refuses_to_load_with_default_secret_in_production():
    # H3: before, a missing JWT_SECRET silently used the published default,
    # letting anyone mint admin tokens.
    env = {k: v for k, v in os.environ.items() if k != "JWT_SECRET"}
    env["APP_ENV"] = "production"
    r = subprocess.run([sys.executable, "-c", "import shared.auth.config"], cwd=ROOT, env=env,
                       capture_output=True, text=True)
    assert r.returncode != 0 and "InsecureConfigError" in r.stderr
    env["JWT_SECRET"] = "s3cret-for-this-deployment"
    r = subprocess.run([sys.executable, "-c", "import shared.auth.config"], cwd=ROOT, env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_only_the_gateway_is_published_on_all_interfaces():
    # H1/H10: Temporal, Kafka, MinIO, MLflow and the services have no auth
    # of their own on those ports — reachable only from the host.
    exposed = []
    for name in ("docker-compose.yml", "docker-compose.override.yml"):
        doc = yaml.safe_load((ROOT / name).read_text())
        for svc, spec in (doc.get("services") or {}).items():
            for port in (spec or {}).get("ports", []) or []:
                if not str(port).startswith("127.0.0.1:"):
                    exposed.append(f"{svc}:{port}")
    assert exposed == ["nginx:8080:80"]


class _FakeRedis:
    def __init__(self):
        self.data = {}

    async def get(self, k):
        return self.data.get(k)

    async def set(self, k, v, ex=None):
        self.data[k] = v


@pytest.mark.asyncio
async def test_idempotency_keys_are_per_user():
    # M3: user B replaying user A's Idempotency-Key must not get A's response.
    redis = _FakeRedis()
    await idempotency.store_response(redis, "svc", "key-1", {"data": {"id": "alice-doc"}}, scope="alice")
    assert await idempotency.get_cached_response(redis, "svc", "key-1", scope="bob") is None
    assert await idempotency.get_cached_response(redis, "svc", "key-1", scope="alice") == {"data": {"id": "alice-doc"}}


def test_nginx_rate_limits_credentials_and_sets_csp():
    conf = (ROOT / "infra/nginx/nginx.conf").read_text()
    limited = {}
    for names, zone in re.findall(r"location ~ \^/api/auth/\(([a-z|-]+)\)\$ \{\s*limit_req zone=(\w+)", conf):
        for name in names.split("|"):
            limited[name] = zone
    for endpoint in ("login", "register", "verify-email", "reset-password", "change-password"):
        assert limited.get(endpoint) == "auth_login", endpoint
    # Endpoints that send an email get the stricter zone.
    for endpoint in ("forgot-password", "resend-verification"):
        assert limited.get(endpoint) == "auth_email", endpoint
    assert re.search(r"zone=auth_email:\S+ rate=\d+r/m", conf)
    # A throttled client gets the platform's JSON error, not nginx's HTML page.
    assert "error_page 429 = @rate_limited" in conf
    assert "Content-Security-Policy" in conf and "script-src 'self'" in conf
