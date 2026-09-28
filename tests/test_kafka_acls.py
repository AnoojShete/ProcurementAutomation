"""Kafka permissions (infra/redpanda/acls.conf) must match what the code
actually publishes and consumes — otherwise the broker silently refuses a
real event, or a service holds a permission it doesn't need."""
import re
from pathlib import Path

import pytest

from shared.kafka_security import kafka_auth_kwargs
from shared.runtime_env import InsecureConfigError

ROOT = Path(__file__).resolve().parent.parent
SERVICES = ["document-vendor-agent", "approval-inventory-agent", "contract-risk-agent", "notification-agent", "auth-service"]


def _acls():
    rules = set()
    for line in (ROOT / "infra/redpanda/acls.conf").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            user, permission, resource, name = line.split()
            rules.add((user, permission, resource, name))
    return rules


def _published(service):
    files = list((ROOT / "services" / service / "app").rglob("*producer*.py"))
    return {t for f in files for t in re.findall(r'TOPIC_[A-Z_]+ = "([a-z._]+)"', f.read_text())}


def _consumed(service):
    f = ROOT / "services" / service / "app" / "kafka" / "consumer.py"
    if not f.exists():
        return set()
    text = f.read_text()
    block = re.search(r"CONSUME_TOPICS = \[(.*?)\]", text, re.S)
    names = set(re.findall(r'"([a-z._]+)"', block.group(1))) if block else set()
    constants = dict(re.findall(r'(TOPIC_[A-Z_]+) = "([a-z._]+)"', text))
    names |= {constants[c] for c in re.findall(r"(TOPIC_[A-Z_]+),", block.group(1))} if block else set()
    return names


def _declared_topics():
    return set(re.findall(r"^\s*-\s*([a-z._]+)\s*$", (ROOT / "shared/kafka-topics.yaml").read_text(), re.M))


@pytest.mark.parametrize("service", SERVICES)
def test_every_published_topic_is_granted(service):
    granted = {n for u, p, r, n in _acls() if u == service and p == "write" and r == "topic"}
    assert _published(service) - granted == set()


@pytest.mark.parametrize("service", SERVICES)
def test_every_consumed_topic_is_granted(service):
    acls = _acls()
    granted = {n for u, p, r, n in acls if u == service and p == "read" and r == "topic"}
    assert _consumed(service) - granted == set()
    if _consumed(service):
        assert (service, "read", "group", service) in acls


@pytest.mark.parametrize("service", SERVICES)
def test_no_permission_beyond_what_the_code_uses(service):
    acls = _acls()
    writes = {n for u, p, r, n in acls if u == service and p == "write"}
    reads = {n for u, p, r, n in acls if u == service and p == "read" and r == "topic"}
    assert writes == _published(service)
    assert reads == _consumed(service)


def test_each_topic_has_one_owner_except_shared_notifications():
    owners = {}
    for u, p, r, n in _acls():
        if p == "write":
            owners.setdefault(n, set()).add(u)
    shared = {n: o for n, o in owners.items() if len(o) > 1}
    assert shared == {"notification.send": {"approval-inventory-agent", "contract-risk-agent"}}
    assert owners["contract.signed"] == {"contract-risk-agent"}


def test_bootstrap_creates_every_topic_the_permissions_mention():
    topics = {n for u, p, r, n in _acls() if r == "topic" and n != "*"}
    assert topics - _declared_topics() == set()


class TestClientCredentials:
    def test_anonymous_allowed_in_development_only(self, monkeypatch):
        monkeypatch.delenv("KAFKA_USERNAME", raising=False)
        monkeypatch.setenv("APP_ENV", "development")
        assert kafka_auth_kwargs() == {}
        monkeypatch.setenv("APP_ENV", "production")
        with pytest.raises(RuntimeError):
            kafka_auth_kwargs()

    def test_credentials_become_sasl_settings(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("KAFKA_USERNAME", "contract-risk-agent")
        monkeypatch.setenv("KAFKA_PASSWORD", "a-real-secret")
        assert kafka_auth_kwargs() == {
            "security_protocol": "SASL_PLAINTEXT", "sasl_mechanism": "SCRAM-SHA-256",
            "sasl_plain_username": "contract-risk-agent", "sasl_plain_password": "a-real-secret",
        }

    def test_published_dev_password_refused_in_production(self, monkeypatch):
        monkeypatch.setenv("KAFKA_USERNAME", "contract-risk-agent")
        monkeypatch.setenv("KAFKA_PASSWORD", "dev-kafka-contract-risk-agent")
        monkeypatch.setenv("APP_ENV", "production")
        with pytest.raises(InsecureConfigError):
            kafka_auth_kwargs()
        monkeypatch.setenv("APP_ENV", "development")
        assert kafka_auth_kwargs()["sasl_plain_username"] == "contract-risk-agent"
