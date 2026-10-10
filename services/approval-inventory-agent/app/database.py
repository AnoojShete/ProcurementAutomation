import asyncio
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

MIGRATIONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "migrations"
)

async def get_db():
    """Dependency for providing a database session."""
    async with async_session_factory() as session:
        yield session

async def init_db():
    """Test the database connection, then apply this service's own schema
    extensions on top of the shared schema (shared/db/init.sql is never
    edited directly). Every statement in migration files is idempotent (IF NOT EXISTS)."""
    try:
        async with engine.begin() as conn:
            pass
        print("Database connection successful")
    except Exception as e:
        print(f"Database connection failed: {e}")
        raise

    if os.path.isdir(MIGRATIONS_DIR):
        # Quote/comment/$$-aware split (shared/db/sql_runner.py).
        from shared.db.sql_runner import split_sql
        migration_files = sorted(f for f in os.listdir(MIGRATIONS_DIR) if f.endswith(".sql"))
        async with engine.begin() as conn:
            for fname in migration_files:
                fpath = os.path.join(MIGRATIONS_DIR, fname)
                with open(fpath, "r", encoding="utf-8") as f:
                    statements = split_sql(f.read())
                for statement in statements:
                    await conn.execute(text(statement))
                print(f"Applied migrations/{fname}")


    # Shared event backbone tables (outbox / inbox / DLQ).
    from shared.eventing import ensure_schema
    await ensure_schema(engine)
