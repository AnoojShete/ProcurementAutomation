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


def kafka_auth_kwargs() -> dict:
    username = os.environ.get("KAFKA_USERNAME", "").strip()
    password = os.environ.get("KAFKA_PASSWORD", "")
    if not username:
        if not is_development():
            raise RuntimeError("KAFKA_USERNAME is not set; services must authenticate to Kafka outside development")
        return {}
    # Outside development, refuse an empty password or a published dev one.
    known = {password} if password.startswith(_DEV_PASSWORD_PREFIX) else set()
    require_secret("KAFKA_PASSWORD", password, known)
    return {
        "security_protocol": "SASL_PLAINTEXT",
        "sasl_mechanism": SASL_MECHANISM,
        "sasl_plain_username": username,
        "sasl_plain_password": password,
    }
