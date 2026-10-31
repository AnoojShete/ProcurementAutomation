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
    # AI second opinion on risk scores (app/services/risk_review.py): a
    # local Ollama model on the host; it flags, never scores.
    risk_review_llm_url: str = "http://host.docker.internal:11434"
    risk_review_model: str = "llama3.2:3b"
    risk_review_timeout_s: float = 90.0
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
    # Where the browser loads Documenso's embedded signing frame from
    # (the API URL is the compose-network one). Unset: the API URL.
    documenso_public_url: str | None = None
    # Documenso's own database, read only for a signer's drawn signature
    # (its API gives none before every party has signed). Unset: the
    # "documenso" database on the same server as database_url.
    documenso_database_url: str | None = None
    # How long the vendor's emailed signing link works.
    vendor_signing_link_days: int = 30
    opensign_api_url: str | None = None

    # DocuSign (optional; sandbox by default). Used when the integration
    # key, user id, account id and RSA private key are all set — see
    # app/services/docusign_client.py and .env.example. Without them,
    # "docusign" sends are simulated like every other provider.
    docusign_integration_key: str | None = None
    docusign_user_id: str | None = None
    docusign_account_id: str | None = None
    # The app's RSA private key: PEM text (newlines may be written as \n)
    # or a path to a mounted PEM file.
    docusign_private_key: str | None = None
    docusign_private_key_file: str | None = None
    docusign_auth_server: str = "account-d.docusign.com"
    docusign_base_url: str = "https://demo.docusign.net/restapi"
    # Must be one of the app's registered redirect URIs; only used to build
    # the one-time consent link shown on the control panel.
    docusign_redirect_uri: str = "https://developers.docusign.com/platform/auth/consent"
    # DocuSign Connect's HMAC key, for POST /webhooks/docusign. Optional:
    # without Connect, the status poller notices completed envelopes.
    docusign_connect_hmac_key: str | None = None
    docusign_poll_seconds: int = 30

    # Drop-folder automation (shared/drop_folder.py): a contract generated
    # for a drop-folder request is sent for signature once, automatically.
    esign_auto_send: bool = True
    # Built-in e-sign: works without any external account. "docusign" /
    # "documenso" still work when those are configured (esign_client.py).
    esign_auto_provider: str = "builtin"
    # Who signs auto-sent contracts. Unset: the vendor's contact email; with
    # neither, the contract stays in draft and the control panel says why.
    esign_auto_signer_email: str | None = None
    esign_auto_signer_name: str = "Authorized Signer"

    model_config = SettingsConfigDict(env_prefix="APP_", env_file=".env", env_file_encoding="utf-8", extra="ignore")



settings = Settings()
# A published webhook secret would let anyone mark contracts signed.
require_secret("APP_ESIGN_WEBHOOK_SECRET", settings.esign_webhook_secret, {DEFAULT_ESIGN_SECRET})

# Shared with approval-inventory-agent for GET /internal/vendors/{id}/clearance.
DEFAULT_INTERNAL_SERVICE_TOKEN = "dev-internal-service-token-change-me"
require_secret("INTERNAL_SERVICE_TOKEN", os.environ.get("INTERNAL_SERVICE_TOKEN"), {DEFAULT_INTERNAL_SERVICE_TOKEN})


@lru_cache
def load_config() -> dict:
    """Load and parse the full config.yaml file."""
    with open(os.path.join(CONFIG_DIR, "config.yaml"), "r") as f:
        return yaml.safe_load(f)


@lru_cache
def load_renewal_config() -> dict:
    return load_config().get("renewal", {})


@lru_cache
def load_offboarding_config() -> dict:
    return load_config().get("offboarding", {})
