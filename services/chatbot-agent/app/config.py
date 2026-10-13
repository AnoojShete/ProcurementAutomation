from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:postgres@postgres:5432/postgres"
    redis_url: str = "redis://redis:6379/0"
    service_name: str = "chatbot-agent"
    llm_api_base_url: str = "http://host.docker.internal:11434"
    llm_model_name: str = "llama3.1"
    orders_api_base_url: str = "http://approval-inventory-agent:8002"

    model_config = SettingsConfigDict(env_prefix="APP_", env_file=".env", extra="ignore")

settings = Settings()