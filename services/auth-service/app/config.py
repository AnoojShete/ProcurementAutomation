from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # NOT prefixed APP_ like the other services — this is its own database
    # (users table), not a query against the shared procurement schema, and
    # AUTH_DATABASE_URL keeps it unambiguous alongside APP_DATABASE_URL in
    # the shared .env.
    database_url: str = "postgresql+asyncpg://postgres:postgres@postgres:5432/postgres"
    service_name: str = "auth-service"
    service_port: int = 8005

    model_config = SettingsConfigDict(env_prefix="AUTH_", env_file=".env", env_file_encoding="utf-8")


settings = Settings()
