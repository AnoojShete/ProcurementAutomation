"""Kafka client credentials.

Each service logs in to Kafka (Redpanda) with its own username and password
(SASL/SCRAM). The broker then checks every request against that service's
permissions in infra/redpanda/acls.conf: a service can only publish to the
topics it owns and read the topics it consumes. So even something already
inside the network can't publish a fake `contract.signed` unless it has
contract-risk-agent's password.

Every AIOKafkaProducer / AIOKafkaConsumer / AIOKafkaAdminClient is created
with `**kafka_auth_kwargs()`. Credentials come from KAFKA_USERNAME and
KAFKA_PASSWORD. Without them a client connects anonymously — allowed only in
development, since unit tests and local runs have no broker credentials.
"""
import os

from shared.runtime_env import is_development, require_secret

SASL_MECHANISM = "SCRAM-SHA-256"
# Development passwords from docker-compose.override.yml ("dev-kafka-<service>").
_DEV_PASSWORD_PREFIX = "dev-kafka-"


def kafka_auth_kwargs(prefix: str = "KAFKA") -> dict:
    """`prefix` picks the login: KAFKA_USERNAME/KAFKA_PASSWORD is the
    service's own; EVENT_MONITOR_KAFKA_* is the read-only event-monitor
    login the control panel's live event log uses."""
    username_var, password_var = f"{prefix}_USERNAME", f"{prefix}_PASSWORD"
    username = os.environ.get(username_var, "").strip()
    password = os.environ.get(password_var, "")
    if not username:
        if not is_development():
            raise RuntimeError(f"{username_var} is not set; services must authenticate to Kafka outside development")
        return {}
    # Outside development, refuse an empty password or a published dev one.
    known = {password} if password.startswith(_DEV_PASSWORD_PREFIX) else set()
    require_secret(password_var, password, known)
    return {
        "security_protocol": "SASL_PLAINTEXT",
        "sasl_mechanism": SASL_MECHANISM,
        "sasl_plain_username": username,
        "sasl_plain_password": password,
    }
