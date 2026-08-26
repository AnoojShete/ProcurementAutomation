import yaml
from decimal import Decimal
from functools import lru_cache
from pydantic import Field, AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://procurement:procurement123@postgres:5432/procurement_db"
    redis_url: str = "redis://redis:6379/0"
    kafka_bootstrap_servers: str = Field(
        "kafka:9092",
        validation_alias=AliasChoices("APP_KAFKA_BOOTSTRAP_SERVERS", "REDPANDA_BROKERS")
    )
    kafka_consumer_group: str = "approval-inventory-agent"
    temporal_host: str = "temporal:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "approval-task-queue"
    service_name: str = "approval-inventory-agent"
    service_port: int = 8002

    model_config = SettingsConfigDict(env_prefix="APP_", env_file=".env", env_file_encoding="utf-8")

settings = Settings()

@lru_cache
def load_config() -> dict:
    """Load and parse the full config.yaml file."""
    with open("config.yaml", "r") as f:
        return yaml.safe_load(f)

@lru_cache
def load_spend_tiers() -> tuple:
    """Extract spend tier rules from config.yaml.
    
    Converts max_amount from YAML int/None to Decimal/None so that
    all downstream comparisons use exact decimal arithmetic (no float).
    Returns a tuple (immutable) so it can be cached by lru_cache.
    """
    config = load_config()
    tiers = []
    for tier in config.get("spend_tiers", []):
        tiers.append({
            "name": tier["name"],
            "max_amount": Decimal(str(tier["max_amount"])) if tier["max_amount"] is not None else None,
            "approval_chain": list(tier["approval_chain"]),
        })
    return tuple(tiers)

