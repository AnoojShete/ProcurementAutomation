import os
from functools import lru_cache
import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from shared.runtime_env import is_development, require_secret

DEFAULT_ESIGN_SECRET = "dev-esign-secret-change-me"

CONFIG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:postgres@postgres:5432/postgres"
    redis_url: str = "redis://redis:6379/0"
    kafka_bootstrap_servers: str = "redpanda:9092"
    kafka_consumer_group: str = "contract-risk-agent"
    temporal_host: str = "temporal:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "contract-risk-task-queue"
    service_name: str = "contract-risk-agent"
    service_port: int = 8003
    mlflow_tracking_uri: str = "http://mlflow:5000"
    esign_provider: str = "self-hosted"
    esign_webhook_secret: str = DEFAULT_ESIGN_SECRET
    # Demo-only "Sign (simulated)" — lets an approver mark a contract signed
    # with no signer. On in development only unless set explicitly.
    allow_simulated_signatures: bool = Field(default_factory=is_development)
    documenso_api_url: str | None = None
    # Documenso API token (Settings -> API Tokens in Documenso) and the
    # secret configured on its webhook, sent back as X-Documenso-Secret.
    documenso_api_token: str | None = None
    documenso_webhook_secret: str | None = None
    opensign_api_url: str | None = None

    model_config = SettingsConfigDict(env_prefix="APP_", env_file=".env", env_file_encoding="utf-8")


settings = Settings()
# A published webhook secret would let anyone mark contracts signed.
require_secret("APP_ESIGN_WEBHOOK_SECRET", settings.esign_webhook_secret, {DEFAULT_ESIGN_SECRET})


@lru_cache
def load_config() -> dict:
    """Load and parse the full config.yaml file."""
    with open(os.path.join(CONFIG_DIR, "config.yaml"), "r") as f:
        return yaml.safe_load(f)


@lru_cache
def load_risk_config() -> dict:
    return load_config().get("risk_model", {})


@lru_cache
def load_renewal_config() -> dict:
    return load_config().get("renewal", {})


@lru_cache
def load_drift_config() -> dict:
    return load_config().get("drift_monitoring", {})


@lru_cache
def load_offboarding_config() -> dict:
    return load_config().get("offboarding", {})
