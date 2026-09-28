import os
from functools import lru_cache
import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from shared.runtime_env import is_development, require_secret

CONFIG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:postgres@postgres:5432/postgres"
    kafka_bootstrap_servers: str = "redpanda:9092"
    # Idempotency-Key cache for uploads (shared/idempotency.py).
    redis_url: str = "redis://redis:6379/0"
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
    # Must not exceed clamd's StreamMaxLength (25 MB by default); a larger
    # stream is refused by clamd and would surface as a misleading 503.
    max_upload_bytes: int = 25 * 1024 * 1024
    # POST /documents/upload/batch limits.
    max_batch_files: int = 20
    max_batch_bytes: int = 100 * 1024 * 1024

    # How many documents one worker process runs through the pipeline at
    # once. More workers (`docker compose up --scale
    # document-vendor-agent-worker=N`) split document.ingested's partitions
    # between them, so the partition count caps total parallel workers.
    worker_concurrency: int = 4
    # Demo-only scenario endpoints (/documents/showcase). On in development
    # (APP_ENV) unless APP_SHOWCASE_MODE says otherwise.
    showcase_mode: bool = Field(default_factory=is_development)
    document_ingested_partitions: int = 6

    # GSTIN live registry (gstincheck.co.in — ~20 free lookups total, not per-day).
    # Always gated by shared/live_mode quota before calling; set this only
    # when live verification is actually needed (demo day).
    gstincheck_api_key: str = ""

    # Hugging Face model cache directory (LayoutLMv3 — ~1 GB download on first use).
    # Mounted as a named Docker volume so the model is not re-downloaded on
    # every container rebuild.
    hf_home: str = "/app/.cache/huggingface"

    model_config = SettingsConfigDict(env_prefix="APP_", env_file=".env", env_file_encoding="utf-8")


settings = Settings()
require_secret("APP_MINIO_SECRET_KEY", settings.minio_secret_key, {"minioadmin"})


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
