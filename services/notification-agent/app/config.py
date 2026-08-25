import os
from functools import lru_cache
import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

CONFIG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:postgres@postgres:5432/postgres"
    kafka_bootstrap_servers: str = "redpanda:9092"
    kafka_consumer_group: str = "notification-agent"
    service_name: str = "notification-agent"
    service_port: int = 8004

    smtp_host: str = "mailpit"
    smtp_port: int = 1025
    smtp_use_tls: bool = False
    email_from: str = "noreply@procurement.local"

    model_config = SettingsConfigDict(env_prefix="APP_", env_file=".env", env_file_encoding="utf-8")


settings = Settings()


@lru_cache
def load_config() -> dict:
    """Load and parse the full config.yaml file."""
    with open(os.path.join(CONFIG_DIR, "config.yaml"), "r") as f:
        return yaml.safe_load(f)


@lru_cache
def default_recipient() -> str:
    return load_config().get("default_recipient", "procurement-ops@example.com")


@lru_cache
def digest_flush_interval_seconds() -> int:
    return int(load_config().get("digest_flush_interval_seconds", 300))


@lru_cache
def urgent_risk_bands() -> list:
    return load_config().get("urgent_risk_bands", ["High"])


@lru_cache
def urgent_renewal_alert_levels() -> list:
    return [str(x) for x in load_config().get("urgent_renewal_alert_levels", ["15"])]
