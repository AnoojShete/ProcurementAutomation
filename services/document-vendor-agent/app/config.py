import os
from functools import lru_cache
import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

CONFIG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:postgres@postgres:5432/postgres"
    kafka_bootstrap_servers: str = "redpanda:9092"
    kafka_consumer_group: str = "document-vendor-agent"
    service_name: str = "document-vendor-agent"
    service_port: int = 8001

    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "documents"
    minio_secure: bool = False

    clamav_host: str = "clamav"
    clamav_port: int = 3310
    clamav_timeout_seconds: int = 15

    model_config = SettingsConfigDict(env_prefix="APP_", env_file=".env", env_file_encoding="utf-8")


settings = Settings()


@lru_cache
def load_config() -> dict:
    """Load and parse the full config.yaml file."""
    with open(os.path.join(CONFIG_DIR, "config.yaml"), "r") as f:
        return yaml.safe_load(f)


@lru_cache
def load_extraction_config() -> dict:
    return load_config().get("extraction", {})


@lru_cache
def load_vendor_matching_config() -> dict:
    return load_config().get("vendor_matching", {})


@lru_cache
def load_duplicate_detection_config() -> dict:
    return load_config().get("duplicate_detection", {})
