import os
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
    pool_recycle=300,
)
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

MIGRATIONS_SQL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "migrations", "0001_schema_extensions.sql"
)


async def get_db():
    """Dependency for providing a database session."""
    async with async_session_factory() as session:
        yield session


MIGRATIONS = (
    "0001_schema_extensions.sql",
    "0002_model_routing_log.sql",
    "0003_vendor_quotes.sql",
    "0004_learning.sql",
    "0005_processing_attempts.sql",
    "0006_integrity.sql",
)


async def _apply_sql_file(path: str) -> None:
    # Quote/comment/$$-aware split (shared/db/sql_runner.py).
    from shared.db.sql_runner import split_sql
    with open(path) as f:
        statements = split_sql(f.read())
    async with engine.begin() as conn:
        for statement in statements:
            await conn.execute(text(statement))


async def init_db():
    """Test the database connection, then apply this service's own schema
    extensions on top of the shared schema (shared/db/init.sql is never
    edited directly). Every statement is idempotent (IF NOT EXISTS), so it's
    safe to layer on top of another service's migration touching the same
    shared tables (vendors, documents, audit_log), same pattern as
    approval-inventory-agent's app/database.py."""
    async with engine.begin() as conn:
        pass

    migrations_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "migrations")
    for name in MIGRATIONS:
        path = os.path.join(migrations_dir, name)
        if os.path.exists(path):
            await _apply_sql_file(path)

    # Shared event backbone tables (outbox / inbox / DLQ).
    from shared.eventing import ensure_schema
    await ensure_schema(engine)
