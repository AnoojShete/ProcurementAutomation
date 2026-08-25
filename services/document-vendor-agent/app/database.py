import os
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.config import settings

engine = create_async_engine(settings.database_url, echo=False)
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

MIGRATIONS_SQL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "migrations", "0001_schema_extensions.sql"
)


async def get_db():
    """Dependency for providing a database session."""
    async with async_session_factory() as session:
        yield session


async def init_db():
    """Test the database connection, then apply this service's own schema
    extensions on top of the shared schema (shared/db/init.sql is never
    edited directly — see migrations/0001_schema_extensions.sql). Every
    statement in that file is idempotent (IF NOT EXISTS), so it's safe to
    layer on top of another service's migration touching the same shared
    tables (vendors, documents, audit_log), same pattern as
    approval-inventory-agent's app/database.py."""
    async with engine.begin() as conn:
        pass

    if os.path.exists(MIGRATIONS_SQL_PATH):
        with open(MIGRATIONS_SQL_PATH) as f:
            raw_sql = f.read()
        # Strip full-line `--` comments before splitting on `;` — a chunk
        # that's comment-only after stripping still passes `if statement`
        # (non-empty string) and asyncpg chokes trying to execute it.
        sql = "\n".join(
            line for line in raw_sql.splitlines() if not line.strip().startswith("--")
        )
        async with engine.begin() as conn:
            for statement in sql.split(";"):
                statement = statement.strip()
                if statement:
                    await conn.execute(text(statement))
