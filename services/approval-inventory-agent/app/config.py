import yaml
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://procurement:procurement123@postgres:5432/procurement_db"
    redis_url: str = "redis://redis:6379/0"
    kafka_bootstrap_servers: str = "kafka:9092"
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
def load_spend_tiers() -> list[dict]:
    """Extract spend tier rules from config.yaml."""
    config = load_config()
    return config.get("spend_tiers", [])
