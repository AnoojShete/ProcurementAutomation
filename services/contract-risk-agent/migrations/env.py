import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Alembic needs a sync driver; the app uses asyncpg, so swap it here.
db_url = os.environ.get(
    "ALEMBIC_DATABASE_URL",
    os.environ.get("APP_DATABASE_URL", "postgresql+asyncpg://postgres:postgres@postgres:5432/postgres"),
).replace("+asyncpg", "+psycopg2")
config.set_main_option("sqlalchemy.url", db_url)

target_metadata = None


def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
